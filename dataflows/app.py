# app.py
# Streamlit app to inspect Dataflow jobs and use Vertex AI (Gemini) for a health summary.
# Includes:
# - Fix A (system_instruction + plain user text)
# - Flashy "OPERATIONS" logo
# - Robust logs (Cloud Logging + Dataflow Job Messages fallback)
# - Error/Warning chips
# - Output validation for BQ and GCS, feeding context into Gemini

import os
import re
import json
import datetime as dt
from typing import List, Dict, Any, Optional, Tuple

import streamlit as st
import pandas as pd

from google.auth import default
from googleapiclient.discovery import build
from google.api_core.exceptions import NotFound

# Vertex AI (Gemini)
import vertexai
from vertexai.generative_models import GenerativeModel

# ---------------------------- Small helpers ----------------------------

def get_env(name: str, default_val: Optional[str] = None) -> str:
    v = os.getenv(name)
    return v if v is not None else (default_val or "")

def render_ops_logo():
    logo_css = """
    <style>
      .ops-wrap { display:flex; flex-direction:column; align-items:center; margin:.25rem 0 1.0rem 0; }
      .ops-logo {
        font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial;
        font-weight: 800;
        font-size: clamp(30px, 6vw, 64px);
        text-transform: uppercase;
        letter-spacing: .14em;
        line-height: 1.05;
        background: linear-gradient(90deg,#00f5ff,#7a5cff,#ff4ecd,#ff9f0a,#00f5ff);
        background-size: 200% 200%;
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        filter: drop-shadow(0 0 6px rgba(122,92,255,.55)) drop-shadow(0 0 22px rgba(255,78,205,.35));
        animation: ops-hue 9s linear infinite, ops-glow 2.4s ease-in-out infinite alternate, ops-gradient 10s ease infinite;
        margin: 0;
      }
      .ops-sub {
        margin-top: .1rem;
        color: #a0a8b8;
        font-size: 12px;
        letter-spacing: .24em;
        text-transform: uppercase;
        opacity: .9;
      }
      @keyframes ops-hue { from { filter: hue-rotate(0deg); } to { filter: hue-rotate(360deg); } }
      @keyframes ops-glow {
        from { text-shadow: 0 0 6px rgba(122,92,255,.6), 0 0 18px rgba(255,78,205,.35); transform: translateY(0); }
        to   { text-shadow: 0 0 12px rgba(0,245,255,.75), 0 0 26px rgba(255,159,10,.35); transform: translateY(-1px); }
      }
      @keyframes ops-gradient {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
      }
    </style>
    """
    html = """
      <div class="ops-wrap">
        <h1 class="ops-logo">Operations</h1>
        <div class="ops-sub">Dataflow • Vertex AI • Observability</div>
      </div>
    """
    st.markdown(logo_css + html, unsafe_allow_html=True)

# ---------------------------- Dataflow: jobs/metrics/messages ----------------------------

@st.cache_data(show_spinner=False, ttl=60)
def list_dataflow_jobs(project_id: str, region: str) -> List[Dict[str, Any]]:
    """
    Returns recent Dataflow jobs (active + terminated in last 7 days)
    """
    creds, _ = default()
    svc = build("dataflow", "v1b3", credentials=creds, cache_discovery=False)

    def _list(filter_val: str):
        req = svc.projects().locations().jobs().list(
            projectId=project_id,
            location=region,
            pageSize=200,
            filter=filter_val
        )
        jobs_ = []
        while req is not None:
            resp = req.execute()
            jobs_.extend(resp.get("jobs", []))
            req = svc.projects().locations().jobs().list_next(previous_request=req, previous_response=resp)
        return jobs_

    jobs = _list("ACTIVE") + _list("TERMINATED")

    # Deduplicate by id
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
        t = j.get("createTime") or j.get("startTime")
        try:
            ts = dt.datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
        except Exception:
            ts = None
        if (ts is None) or (ts >= cutoff.replace(tzinfo=ts.tzinfo if ts else None)):
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
def get_recent_logs(
    project_id: str,
    job_id: str,
    region: str,
    severity_min: str = "ERROR",
    lookback_minutes: int = 240,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """
    Cloud Logging: logs for this job_id in region (resource.type in {dataflow_job, dataflow_step})
    """
    from google.cloud import logging as gcloud_logging
    client = gcloud_logging.Client(project=project_id)

    sev = severity_min.upper()
    if sev not in {"INFO", "WARNING", "ERROR"}:
        sev = "ERROR"
    end = dt.datetime.utcnow()
    start = end - dt.timedelta(minutes=lookback_minutes)

    filter_str = f"""
timestamp >= "{start.isoformat()}Z"
timestamp <= "{end.isoformat()}Z"
severity >= {sev}
(
  resource.type="dataflow_job"  AND resource.labels.job_id="{job_id}" AND resource.labels.region="{region}"
) OR (
  resource.type="dataflow_step" AND resource.labels.job_id="{job_id}" AND resource.labels.region="{region}"
)
""".strip()

    entries = list(client.list_entries(filter_=filter_str, order_by=gcloud_logging.DESCENDING))
    out = []
    for e in entries[:limit]:
        payload = e.payload
        if not isinstance(payload, str):
            try:
                payload = json.dumps(payload, default=str)
            except Exception:
                payload = str(e.payload)
        out.append({
            "timestamp": getattr(e, "timestamp", "") and e.timestamp.isoformat(),
            "severity": str(getattr(e, "severity", "")),
            "message": payload[:4000],
            "log_name": getattr(e, "log_name", ""),
        })
    return out


@st.cache_data(show_spinner=False, ttl=60)
def get_job_messages(
    project_id: str,
    region: str,
    job_id: str,
    minimum_importance: str = "JOB_MESSAGE_WARNING",
    lookback_minutes: int = 4320
) -> List[Dict[str, Any]]:
    """
    Fallback: Dataflow Job Messages API (warnings/errors) independent of Cloud Logging.
    """
    creds, _ = default()
    svc = build("dataflow", "v1b3", credentials=creds, cache_discovery=False)

    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    start = end - dt.timedelta(minutes=lookback_minutes)

    req = svc.projects().locations().jobs().messages().list(
        projectId=project_id,
        location=region,
        jobId=job_id,
        minimumImportance=minimum_importance,
        startTime=start.isoformat().replace("+00:00", "Z"),
        pageSize=1000,
    )

    msgs = []
    while req is not None:
        resp = req.execute()
        for m in resp.get("jobMessages", []):
            msgs.append({
                "time": m.get("time"),
                "messageImportance": m.get("messageImportance"),
                "messageText": m.get("messageText", "")[:4000],
            })
        req = svc.projects().locations().jobs().messages().list_next(previous_request=req, previous_response=resp)

    msgs.sort(key=lambda x: x.get("time") or "", reverse=True)
    return msgs


def normalize_job_messages_for_ai(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map Dataflow job messages into the same shape as Cloud Logging entries for Gemini."""
    sev_map = {
        "JOB_MESSAGE_ERROR": "ERROR",
        "JOB_MESSAGE_WARNING": "WARNING",
        "JOB_MESSAGE_DEBUG": "INFO",
        "JOB_MESSAGE_DETAILED": "INFO",
        "JOB_MESSAGE_BASIC": "INFO",
    }
    out = []
    for m in msgs:
        out.append({
            "timestamp": m.get("time"),
            "severity": sev_map.get(m.get("messageImportance", ""), "INFO"),
            "message": m.get("messageText", ""),
        })
    return out


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
    state_order = {"JOB_STATE_RUNNING": 0, "JOB_STATE_DRAINING": 1, "JOB_STATE_QUEUED": 2}
    df["state_sort"] = df["State"].map(lambda s: state_order.get(s, 9))
    df = df.sort_values(by=["state_sort", "Created"], ascending=[True, False]).drop(columns=["state_sort"])
    return df

# ---------------------------- Output validation (BQ & GCS) ----------------------------

def infer_output_targets(job: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Infer an output BigQuery table or GCS prefix from pipeline options/labels.
    Returns {"bq_table": "project.dataset.table" or None, "gcs_prefix": "gs://bucket/prefix" or None}
    """
    params = (job.get("environment", {}) or {}).get("sdkPipelineOptions", {}) or {}
    labels = job.get("labels", {}) or {}

    candidates = []
    keys = [
        "outputTable", "output_table", "bigQueryTable", "bq_table", "table",
        "output", "outputPath", "output_prefix", "gcsOutputPath", "sink", "destination"
    ]
    for k in keys:
        v = params.get(k) or labels.get(k)
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())

    bq_table = None
    gcs_prefix = None
    for c in candidates:
        if re.match(r"^[\w\-]+[:.][\w$]+[.][\w$]+$", c):
            bq_table = c.replace(":", ".")
            break
    for c in candidates:
        if c.startswith("gs://"):
            gcs_prefix = c.rstrip("/")
            break

    return {"bq_table": bq_table, "gcs_prefix": gcs_prefix}

def parse_gs_path(gs_uri: str) -> Tuple[str, str]:
    m = re.match(r"^gs://([^/]+)/(.*)$", gs_uri)
    if not m:
        raise ValueError("Invalid GCS URI (expected gs://bucket/prefix)")
    return m.group(1), m.group(2)

@st.cache_data(show_spinner=False, ttl=60)
def bq_quick_validation(project_id: str, table: str, min_rows: int = 1,
                        not_null_column: Optional[str] = None,
                        max_null_rate: float = 0.0, sample_limit: int = 10) -> Dict[str, Any]:
    try:
        from google.cloud import bigquery
    except ImportError:
        return {"ok": False, "error": "google-cloud-bigquery not installed. Add it to requirements.txt."}

    client = bigquery.Client(project=project_id)

    cnt_sql = f"SELECT COUNT(*) AS c FROM `{table}`"
    cnt = list(client.query(cnt_sql).result())[0]["c"]

    nn_rate = None
    if not_null_column:
        nn_sql = f"""
        SELECT 1.0 * COUNTIF({not_null_column} IS NULL) / NULLIF(COUNT(*),0) AS null_rate
        FROM `{table}`
        """
        nn_rate = list(client.query(nn_sql).result())[0]["null_rate"] or 0.0

    sample_sql = f"SELECT * FROM `{table}` LIMIT {sample_limit}"
    sample = [dict(r.items()) for r in client.query(sample_sql).result()]

    ok = True
    reasons = []
    if cnt < min_rows:
        ok = False
        reasons.append(f"Row count {cnt} < min_rows {min_rows}.")
    if not_null_column is not None and nn_rate is not None and nn_rate > max_null_rate:
        ok = False
        reasons.append(f"Null rate for `{not_null_column}` is {nn_rate:.2%} > allowed {max_null_rate:.2%}.")

    return {
        "ok": ok,
        "row_count": int(cnt),
        "null_rate": float(nn_rate) if nn_rate is not None else None,
        "sample": sample,
        "reasons": reasons,
    }

@st.cache_data(show_spinner=False, ttl=60)
def gcs_quick_validation(gs_prefix: str, min_files: int = 1, min_total_bytes: int = 1_024) -> Dict[str, Any]:
    try:
        from google.cloud import storage
    except ImportError:
        return {"ok": False, "error": "google-cloud-storage not installed. Add it to requirements.txt."}

    bucket_name, prefix = parse_gs_path(gs_prefix)
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    total = 0
    files = 0
    blobs = []
    for b in client.list_blobs(bucket, prefix=prefix + "/"):
        files += 1
        total += int(b.size or 0)
        if len(blobs) < 10:
            blobs.append({"name": b.name, "size": int(b.size or 0), "updated": str(b.updated)})

    ok = True
    reasons = []
    if files < min_files:
        ok = False
        reasons.append(f"Only {files} file(s) found under {gs_prefix}, expected ≥ {min_files}.")
    if total < min_total_bytes:
        ok = False
        reasons.append(f"Total size {total}B < minimum {min_total_bytes}B.")

    return {"ok": ok, "files": files, "total_bytes": total, "sample": blobs, "reasons": reasons}

# ---------------------------- Vertex AI: Fix A ----------------------------

def gemini_summarize(
    project_id: str,
    vertex_region: str,
    job: Dict[str, Any],
    metrics: Dict[str, Any],
    errors: List[Dict[str, Any]],
    validation_note: Optional[str] = None,
) -> str:
    """
    Use Vertex Gemini to summarize job health & next actions.
    FIX A: Use system_instruction + plain user text to avoid Part type errors.
    """
    vertexai.init(project=project_id, location=vertex_region)

    system_msg = (
        "You are a GCP Dataflow reliability assistant. "
        "Given a Dataflow job summary, metrics and recent error logs, "
        "produce a concise health summary with: "
        "1) Current status & likely cause, 2) Impact (if any), "
        "3) Top 3 next steps with concrete GCP Console or gcloud paths, "
        "4) If healthy, recommended validations."
    )

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
    error_texts = [
        f'{e.get("timestamp","")} [{e.get("severity","")}]: {e.get("message","")}'
        for e in errors[:10]
    ]

    user_msg = f"""
JOB:
{json.dumps(job_core, indent=2)}

METRICS (truncated):
{json.dumps(metric_summ[:30], indent=2)}

RECENT LOGS/JOB MESSAGES (up to 10):
{json.dumps(error_texts, indent=2)}
"""

    if validation_note:
        user_msg += f"\nOUTPUT VALIDATION CONTEXT:\n{validation_note}\n"

    model = GenerativeModel("gemini-1.5-pro", system_instruction=system_msg)
    resp = model.generate_content(user_msg, generation_config={"temperature": 0.2, "max_output_tokens": 1024})

    try:
        return resp.text
    except AttributeError:
        return resp.candidates[0].content.parts[0].text

# ---------------------------- UI ----------------------------

st.set_page_config(page_title="Dataflow Health (Vertex AI)", page_icon="🎛️", layout="wide")
render_ops_logo()
st.title("⚙️ Dataflow Health — Vertex AI Assisted")

# Sidebar
with st.sidebar:
    st.header("Settings")
    project_id = st.text_input("Project ID", value=get_env("PROJECT_ID"))
    region = st.text_input("Dataflow Region", value=get_env("DATAFLOW_REGION", "us-central1"))
    vertex_region = st.text_input("Vertex AI Region", value=get_env("VERTEX_REGION", region))
    lookback = st.number_input("Log Lookback (minutes)", min_value=15, max_value=4320, value=240, step=15)
    severity_min = st.selectbox("Minimum severity (Cloud Logging)", ["ERROR", "WARNING", "INFO"], index=0)
    st.caption("Tip: Increase lookback or lower severity if you don't see entries.")

if not project_id:
    st.info("Set PROJECT_ID (sidebar or env var).")
    st.stop()

# Session state for validation result note
if "validation_note" not in st.session_state:
    st.session_state["validation_note"] = None

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

# Inspect a job
st.markdown("---")
st.subheader("Inspect a Job")

job_names = [f'{j.get("name")} ({j.get("id")})' for j in jobs]
sel = st.selectbox("Select job", options=job_names, index=0)
sel_job = jobs[job_names.index(sel)]
sel_job_id = sel_job.get("id")

console_url = f"https://console.cloud.google.com/dataflow/jobs/locations/{region}/jobs/{sel_job_id}?project={project_id}"
st.markdown(f"[Open in Google Cloud Console ↗]({console_url})")

cols = st.columns([1, 1, 1, 1, 1])
with cols[0]:
    if st.button("Refresh Metrics & Logs"):
        st.cache_data.clear()

# Fetch metrics
with st.spinner("Getting metrics…"):
    try:
        metrics = get_job_metrics(project_id, region, sel_job_id)
    except NotFound:
        metrics = {}
    except Exception as e:
        st.error(f"Error fetching metrics: {e}")
        metrics = {}

# Fetch logs + fallback
with st.spinner("Getting logs/messages…"):
    logs = get_recent_logs(project_id, sel_job_id, region, severity_min, lookback, limit=300)
    errors_for_ai: List[Dict[str, Any]] = logs[:]  # default

    used_fallback = False
    if not logs:
        jmsgs = get_job_messages(project_id, region, sel_job_id, minimum_importance="JOB_MESSAGE_WARNING", lookback_minutes=max(lookback, 1440))
        if jmsgs:
            errors_for_ai = normalize_job_messages_for_ai(jmsgs)
            used_fallback = True
        else:
            errors_for_ai = []

# Show metrics + logs
mcol1, mcol2 = st.columns([1, 1])

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
    if not used_fallback:
        st.markdown("**Recent Logs for this Job (Cloud Logging)**")
        edf = pd.DataFrame(logs)
        if not edf.empty:
            err_count = int((edf["severity"] == "ERROR").sum()) if "severity" in edf else 0
            warn_count = int((edf["severity"] == "WARNING").sum()) if "severity" in edf else 0
            info_count = int((edf["severity"] == "INFO").sum()) if "severity" in edf else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Errors", err_count)
            c2.metric("Warnings", warn_count)
            c3.metric("Info", info_count)
            st.dataframe(edf, use_container_width=True, hide_index=True)
        else:
            st.info("No Cloud Logging entries matched the filters.")
    else:
        st.markdown("**Dataflow Job Messages (fallback)**")
        jdf = pd.DataFrame(errors_for_ai)
        if not jdf.empty:
            err_count = int((jdf["severity"] == "ERROR").sum())
            warn_count = int((jdf["severity"] == "WARNING").sum())
            c1, c2 = st.columns(2)
            c1.metric("Errors (Job Messages)", err_count)
            c2.metric("Warnings (Job Messages)", warn_count)
            st.dataframe(jdf, use_container_width=True, hide_index=True)
        else:
            st.warning("No job messages found either. Try increasing lookback or lowering severity.")

# ---------------------------- Output Validation ----------------------------

st.markdown("---")
st.subheader("Output Validation")

infer = infer_output_targets(sel_job)
bq_table_default = infer.get("bq_table") or ""
gcs_prefix_default = infer.get("gcs_prefix") or ""

vcol1, vcol2 = st.columns(2)
with vcol1:
    bq_table = st.text_input("BigQuery table (project.dataset.table)", value=bq_table_default, placeholder="my-proj.my_ds.my_table")
    min_rows = st.number_input("Min row count", min_value=0, value=1, step=1)
    not_null_col = st.text_input("Key column must be NOT NULL (optional)", value="")
    max_null_rate = st.slider("Allowed NULL rate for key column", 0.0, 1.0, 0.0, 0.01)
with vcol2:
    gcs_prefix = st.text_input("GCS output prefix (gs://bucket/path)", value=gcs_prefix_default, placeholder="gs://my-bucket/my-path")
    min_files = st.number_input("Min # files", min_value=0, value=1, step=1)
    min_total_bytes = st.number_input("Min total bytes", min_value=0, value=1024, step=1024)

run_bq = st.button("Run BigQuery Validation")
run_gcs = st.button("Run GCS Validation")

if run_bq and bq_table:
    with st.spinner("Validating BigQuery output…"):
        res = bq_quick_validation(
            project_id=project_id, table=bq_table,
            min_rows=min_rows,
            not_null_column=(not_null_col or None),
            max_null_rate=max_null_rate,
            sample_limit=10
        )
    if res.get("error"):
        st.error(res["error"])
    else:
        v1, v2 = st.columns(2)
        v1.metric("Row Count", f'{res["row_count"]:,}')
        if res.get("null_rate") is not None:
            v2.metric("Null Rate", f'{res["null_rate"]:.2%}')
        st.success("✅ Output looks OK" if res["ok"] else "❌ Validation failed")
        if res.get("reasons"):
            st.write("Reasons:", res["reasons"])
        if res.get("sample"):
            st.markdown("**Sample rows**")
            st.dataframe(pd.DataFrame(res["sample"]), use_container_width=True, hide_index=True)
        st.session_state["validation_note"] = f"BQ validation ok={res['ok']}, rows={res['row_count']}, null_rate={res.get('null_rate')}, reasons={res.get('reasons')}"

if run_gcs and gcs_prefix:
    with st.spinner("Validating GCS output…"):
        res = gcs_quick_validation(gcs_prefix, min_files=min_files, min_total_bytes=min_total_bytes)
    if res.get("error"):
        st.error(res["error"])
    else:
        v1, v2 = st.columns(2)
        v1.metric("Files", f'{res["files"]:,}')
        v2.metric("Total Bytes", f'{res["total_bytes"]:,}')
        st.success("✅ Output looks OK" if res["ok"] else "❌ Validation failed")
        if res.get("reasons"):
            st.write("Reasons:", res["reasons"])
        if res.get("sample"):
            st.markdown("**Sample objects**")
            st.dataframe(pd.DataFrame(res["sample"]), use_container_width=True, hide_index=True)
        st.session_state["validation_note"] = f"GCS validation ok={res['ok']}, files={res['files']}, total_bytes={res['total_bytes']}, reasons={res.get('reasons')}"

# ---------------------------- Vertex AI Health Summary ----------------------------

st.markdown("---")
st.subheader("Vertex AI Health Summary")

if st.button("Analyze with Vertex AI (Gemini)"):
    with st.spinner("Calling Vertex AI…"):
        try:
            summary = gemini_summarize(
                project_id, vertex_region, sel_job, metrics, errors_for_ai,
                validation_note=st.session_state.get("validation_note")
            )
            st.markdown("### Result")
            st.write(summary)
        except Exception as e:
            st.error(f"Vertex AI analysis failed: {e}")

st.caption("Powered by Streamlit • Dataflow API • Cloud Logging • Vertex AI Gemini")
