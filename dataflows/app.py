import os
import time
import json
import datetime as dt
from typing import List, Dict, Any, Optional

import streamlit as st
import pandas as pd

from google.auth import default
from googleapiclient.discovery import build
from google.cloud import logging as gcloud_logging
from google.api_core.exceptions import NotFound

# --- Vertex AI (Gemini) ---
import vertexai
from vertexai.generative_models import GenerativeModel

# ---------------------------- Utilities ----------------------------

def get_env(name: str, default_val: Optional[str] = None) -> str:
    v = os.getenv(name)
    return v if v is not None else (default_val or "")

@st.cache_data(show_spinner=False, ttl=60)
def list_dataflow_jobs(project_id: str, region: str) -> List[Dict[str, Any]]:
    """
    Returns recent Dataflow jobs (active + terminated in last 7 days)
    """
    creds, _ = default()
    svc = build("dataflow", "v1b3", credentials=creds, cache_discovery=False)
    request = svc.projects().locations().jobs().list(
        projectId=project_id,
        location=region,
        pageSize=200,
        filter="ACTIVE"  # we'll fetch ACTIVE first, then TERMINATED
    )

    jobs = []
    while request is not None:
        resp = request.execute()
        jobs.extend(resp.get("jobs", []))
        request = svc.projects().locations().jobs().list_next(previous_request=request, previous_response=resp)

    # also pull TERMINATED jobs (recent history)
    request = svc.projects().locations().jobs().list(
        projectId=project_id,
        location=region,
        pageSize=200,
        filter="TERMINATED"
    )
    while request is not None:
        resp = request.execute()
        jobs.extend(resp.get("jobs", []))
        request = svc.projects().locations().jobs().list_next(previous_request=request, previous_response=resp)

    # Deduplicate by id (ACTIVE can also appear as TERMINATED in rare race windows)
    seen = set()
    unique = []
    for j in jobs:
        jid = j.get("id") or j.get("jobUuid")
        if jid and jid not in seen:
            seen.add(jid)
            unique.append(j)

    # Keep only last 7 days
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=7)
    pruned = []
    for j in unique:
        # try to parse startTime or createTime
        t = j.get("createTime") or j.get("startTime")
        try:
            ts = dt.datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
        except Exception:
            ts = None
        if (ts is None) or (ts >= cutoff.replace(tzinfo=ts.tzinfo)):
            pruned.append(j)

    return pruned

@st.cache_data(show_spinner=False, ttl=60)
def get_job_metrics(project_id: str, region: str, job_id: str) -> Dict[str, Any]:
    """
    Calls projects.locations.jobs.getMetrics
    """
    creds, _ = default()
    svc = build("dataflow", "v1b3", credentials=creds, cache_discovery=False)
    resp = svc.projects().locations().jobs().getMetrics(
        projectId=project_id, location=region, jobId=job_id
    ).execute()
    return resp

@st.cache_data(show_spinner=False, ttl=60)
def get_recent_error_logs(project_id: str, job_id: str, lookback_minutes: int = 120, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Pull recent ERROR logs for the Dataflow job_id from Cloud Logging.
    """
    client = gcloud_logging.Client(project=project_id)
    logger = client.logger("dataflow")  # not strictly necessary

    # Dataflow logs usually use one of these resources:
    # - resource.type="dataflow_step" with labels job_id, project_id, region, step_id
    # - resource.type="dataflow_job"  (newer)
    # We’ll OR the two types, filtered by job_id.
    end = dt.datetime.utcnow()
    start = end - dt.timedelta(minutes=lookback_minutes)
    filter_str = f'''
        timestamp >= "{start.isoformat()}Z"
        timestamp <= "{end.isoformat()}Z"
        severity >= ERROR
        (
          resource.type="dataflow_step" AND resource.labels.job_id="{job_id}"
        ) OR (
          resource.type="dataflow_job" AND resource.labels.job_id="{job_id}"
        )
    '''.strip()

    entries = list(client.list_entries(filter_=filter_str, order_by=gcloud_logging.DESCENDING))
    out = []
    for e in entries[:limit]:
        out.append({
            "timestamp": e.timestamp.isoformat() if e.timestamp else "",
            "severity": str(e.severity),
            "message": e.payload if isinstance(e.payload, str) else json.dumps(e.payload, default=str)[:2000],
            "trace": getattr(e, "trace", None),
        })
    return out

def init_vertex(project_id: str, region: str):
    vertexai.init(project=project_id, location=region)

def gemini_summarize(project_id: str, vertex_region: str, job: Dict[str, Any], metrics: Dict[str, Any], errors: List[Dict[str, Any]]) -> str:
    """
    Use Vertex Gemini to summarize job health & next actions.
    """
    init_vertex(project_id, vertex_region)
    model = GenerativeModel("gemini-1.5-pro")

    job_core = {
        "id": job.get("id"),
        "name": job.get("name"),
        "type": job.get("type"),
        "currentState": job.get("currentState"),
        "createTime": job.get("createTime"),
        "startTime": job.get("startTime"),
        "endTime": job.get("endTime"),
        "location": job.get("location"),
        "labels": job.get("labels", {}),
        "parameters": job.get("environment", {}).get("sdkPipelineOptions", {}),
    }

    metric_summ = metrics.get("metrics", [])
    error_texts = [f'{e.get("timestamp","")} [{e.get("severity","")}]: {e.get("message","")}' for e in errors[:10]]

    system_msg = (
        "You are a GCP Dataflow reliability assistant. "
        "Given a Dataflow job summary, metrics and recent error logs, "
        "produce a concise health summary with: "
        "1) Current status & likely cause, 2) Impact (if any), "
        "3) Top 3 next steps with concrete GCP console or CLI paths, "
        "4) If healthy, recommended validations."
    )

    user_msg = f"""
JOB:
{json.dumps(job_core, indent=2)}

METRICS (truncated):
{json.dumps(metric_summ[:30], indent=2)}

RECENT ERROR LOGS (up to 10):
{json.dumps(error_texts, indent=2)}
"""

    resp = model.generate_content(
        [
            {"role": "system", "parts": [system_msg]},
            {"role": "user", "parts": [user_msg]},
        ],
        safety_settings=None,
    )
    return resp.text if hasattr(resp, "text") else str(resp)

def fmt_jobs_df(jobs: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for j in jobs:
        rows.append({
            "Job Name": j.get("name"),
            "Job ID": j.get("id"),
            "Type": j.get("type"),
            "State": j.get("currentState"),
            "Region": j.get("location"),
            "Created": j.get("createTime"),
            "Started": j.get("startTime"),
            "Ended": j.get("endTime"),
            "Labels": json.dumps(j.get("labels", {})),
        })
    df = pd.DataFrame(rows)
    # nice sort: active first, then recent
    state_order = {"JOB_STATE_RUNNING": 0, "JOB_STATE_DRAINING": 1, "JOB_STATE_QUEUED": 2}
    df["state_sort"] = df["State"].map(lambda s: state_order.get(s, 9))
    df = df.sort_values(by=["state_sort", "Created"], ascending=[True, False]).drop(columns=["state_sort"])
    return df

# ---------------------------- UI ----------------------------

st.set_page_config(page_title="Dataflow Health (Vertex AI)", page_icon="⚙️", layout="wide")

st.title("⚙️ Dataflow Health — Vertex AI Assisted")

with st.sidebar:
    st.header("Settings")
    project_id = st.text_input("Project ID", value=get_env("PROJECT_ID"))
    region = st.text_input("Dataflow Region", value=get_env("DATAFLOW_REGION", "us-central1"))
    vertex_region = st.text_input("Vertex AI Region", value=get_env("VERTEX_REGION", region))
    lookback = st.number_input("Error Log Lookback (minutes)", min_value=15, max_value=1440, value=120, step=15)

    st.caption("These should match your Cloud Run service env vars / service account permissions.")

if not project_id:
    st.info("Set PROJECT_ID (sidebar or env var).")
    st.stop()

with st.spinner("Fetching Dataflow jobs…"):
    try:
        jobs = list_dataflow_jobs(project_id, region)
    except Exception as e:
        st.error(f"Failed to list Dataflow jobs: {e}")
        st.stop()

if not jobs:
    st.warning("No recent Dataflow jobs (last 7 days).")
    st.stop()

df = fmt_jobs_df(jobs)
st.subheader("Jobs")
st.dataframe(df, use_container_width=True, hide_index=True)

# Selection row
st.markdown("---")
st.subheader("Inspect a Job")

job_names = [f'{j.get("name")} ({j.get("id")})' for j in jobs]
sel = st.selectbox("Select job", options=job_names, index=0)
sel_job = jobs[job_names.index(sel)]
sel_job_id = sel_job.get("id")

cols = st.columns([1,1,1,1,1])
with cols[0]:
    if st.button("Refresh Metrics & Logs"):
        st.cache_data.clear()

with st.spinner("Getting metrics…"):
    try:
        metrics = get_job_metrics(project_id, region, sel_job_id)
    except NotFound:
        metrics = {}
    except Exception as e:
        st.error(f"Error fetching metrics: {e}")
        metrics = {}

with st.spinner("Getting recent error logs…"):
    try:
        errors = get_recent_error_logs(project_id, sel_job_id, lookback_minutes=lookback, limit=50)
    except Exception as e:
        st.error(f"Error fetching error logs: {e}")
        errors = []

mcol1, mcol2 = st.columns([1,1])
with mcol1:
    st.markdown("**Metrics (truncated view)**")
    metrics_list = metrics.get("metrics", [])
    mdf = pd.DataFrame([{
        "Name": m.get("name"),
        "Scalar": m.get("scalar"),
        "Update Time": m.get("updateTime"),
        "Kind": m.get("kind")
    } for m in metrics_list[:50]])
    if not mdf.empty:
        st.dataframe(mdf, use_container_width=True, hide_index=True)
    else:
        st.info("No metrics returned.")

with mcol2:
    st.markdown("**Recent Error Logs**")
    edf = pd.DataFrame(errors)
    if not edf.empty:
        st.dataframe(edf, use_container_width=True, hide_index=True)
    else:
        st.info("No error logs in the selected lookback window.")

st.markdown("---")
st.subheader("Vertex AI Health Summary")

if st.button("Analyze with Vertex AI (Gemini)"):
    with st.spinner("Calling Vertex AI…"):
        try:
            summary = gemini_summarize(project_id, vertex_region, sel_job, metrics, errors)
            st.markdown("### Result")
            st.write(summary)
        except Exception as e:
            st.error(f"Vertex AI analysis failed: {e}")
            st.stop()

st.caption("Powered by Streamlit • Dataflow API • Cloud Logging • Vertex AI Gemini")
