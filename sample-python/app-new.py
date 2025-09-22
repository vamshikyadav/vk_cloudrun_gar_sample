import os
import re
import time
import json
import requests
import streamlit as st

# ===================
# 🔧 Config
# ===================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
OWNER = os.getenv("GITHUB_OWNER", "your-org").strip()
REPO = os.getenv("GITHUB_REPO", "your-repo").strip()
BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

WORKFLOWS = {
    "Blue-Green Autoswitch": "bluegreen.yaml",
    "Blue-Green Test Automation": "blue-green-test.yaml",
}

headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# ===================
# 📝 GitHub API Helpers
# ===================
def get_apps():
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/contents/helm-chart?ref={BRANCH}"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return [item["name"] for item in r.json() if item.get("type") == "dir"]

def trigger_workflow(workflow_file, inputs):
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": BRANCH, "inputs": inputs}
    return requests.post(url, headers=headers, json=payload)

def get_latest_run(workflow_file):
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/runs"
    params = {"branch": BRANCH, "event": "workflow_dispatch", "per_page": 5}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        return None
    runs = r.json().get("workflow_runs", [])
    return runs[0] if runs else None

def get_run_jobs(run_id):
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs"
    r = requests.get(url, headers=headers)
    return r.json().get("jobs", []) if r.status_code == 200 else []

def get_job_logs(job_id):
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/jobs/{job_id}/logs"
    r = requests.get(url, headers=headers, allow_redirects=True)
    return r.text if r.status_code == 200 else ""

def extract_pr_url(logs):
    m = re.search(r"https://github\.com/[^\s]+/pull/\d+", logs)
    return m.group(0) if m else None

# ===================
# 🎨 Streamlit UI
# ===================
st.set_page_config(page_title="Blue-Green Deployment Panel", layout="wide")

st.markdown(
    """
    <style>
    .card {
        background-color: #fbeaea;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style="text-align:center; padding:15px; background:linear-gradient(90deg,#8e0e00,#b92b27); color:white; border-radius:12px;">
      <h1>🚀 Blue-Green Deployment Panel</h1>
      <p>Trigger autoswitch or test automation with per-service version control</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Workflow choice
workflow_choice = st.selectbox("Select Workflow", list(WORKFLOWS.keys()))
workflow_file = WORKFLOWS[workflow_choice]

# Apps
apps = []
try:
    apps = get_apps()
except Exception as e:
    st.error(f"❌ Failed to load apps: {e}")

# Inputs
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("⚙️ Workflow Inputs")

if workflow_choice == "Blue-Green Autoswitch":
    col1, col2 = st.columns(2)
    with col1:
        update_primary = st.checkbox("Update Primary", value=False)
        update_standy = st.checkbox("Update Standby", value=False)
    with col2:
        autoflip = st.checkbox("Auto Flip", value=False)
        turnoffstandby = st.checkbox("Turn Off Standby", value=False)

    businessunit = st.selectbox("Business Unit", ["us", "uk", "eu", "apac"])
    environment = st.selectbox("Environment", ["dev", "qa", "int", "prod"])

    selected_apps = st.multiselect("Deployment Services (Apps)", apps)
    versions = {}
    if selected_apps:
        st.write("### Per-App Versions")
        for app in selected_apps:
            versions[app] = st.text_input(f"Version for {app}", value="1.0.0")

elif workflow_choice == "Blue-Green Test Automation":
    selectforautomation = st.checkbox("Select for Automation", value=False)
    selectrelease = st.selectbox("Release (Business Unit)", ["us", "uk", "eu", "apac"])
    selectenvironment = st.selectbox("Environment", ["dev", "qa", "int", "prod"])
    selected_apps = st.multiselect("Services (Apps)", apps)
    selectrunstandby = st.checkbox("Run Standby", value=False)
st.markdown('</div>', unsafe_allow_html=True)

# Trigger
st.markdown('<div class="card">', unsafe_allow_html=True)
if st.button("🔥 Trigger Workflow(s)"):
    if not selected_apps:
        st.warning("⚠️ Select at least one app")
    else:
        for app in selected_apps:
            if workflow_choice == "Blue-Green Autoswitch":
                inputs = {
                    "version": versions.get(app, "1.0.0"),
                    "update_primary": str(update_primary).lower(),
                    "update_standy": str(update_standy).lower(),
                    "autoflip": str(autoflip).lower(),
                    "turnoffstandby": str(turnoffstandby).lower(),
                    "businessunit": businessunit,
                    "environment": environment,
                    "deployment_service": app,
                }
            else:  # Test automation
                inputs = {
                    "selectforautomation": str(selectforautomation).lower(),
                    "selectrelease": selectrelease,
                    "selectenvironment": selectenvironment,
                    "selectservice": app,
                    "selectrunstandby": str(selectrunstandby).lower(),
                }

            st.write(f"📤 Sending inputs for **{app}**:", inputs)
            resp = trigger_workflow(workflow_file, inputs)
            if resp.status_code != 204:
                st.error(f"❌ Failed for {app}: {resp.status_code} - {resp.text}")
                continue

            st.success(f"✅ Workflow triggered for {app}")
            time.sleep(3)
            run = get_latest_run(workflow_file)
            if not run:
                st.warning("Run not found yet. Check Actions UI.")
                continue

            st.markdown(f"🔗 [View run for {app}]({run['html_url']})")
            st.write(f"📊 Status: {run['status']} | Conclusion: {run.get('conclusion')}")

            # Look for PR link
            jobs = get_run_jobs(run["id"])
            for job in jobs:
                for step in job.get("steps", []):
                    if "PR" in step.get("name", "") and step.get("conclusion") == "success":
                        logs = get_job_logs(job["id"])
                        pr_url = extract_pr_url(logs)
                        if pr_url:
                            st.success(f"📎 PR Created: [Open PR]({pr_url})")
                        else:
                            st.info("ℹ️ PR created but URL not found in logs")
st.markdown('</div>', unsafe_allow_html=True)
