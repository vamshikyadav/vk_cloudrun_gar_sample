import streamlit as st
import requests
import os
import json
import time
import re

# ===================
# 🔑 GitHub settings
# ===================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
OWNER = "your-org"   # 🔥 change me
REPO = "your-repo"   # 🔥 change me
BRANCH = "main"

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
    """Fetch list of app directories under helm-chart/"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/helm-chart"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return [item["name"] for item in r.json() if item["type"] == "dir"]

def trigger_workflow(workflow_file, inputs):
    """Trigger workflow_dispatch"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": BRANCH, "inputs": inputs}
    r = requests.post(url, headers=headers, json=payload)
    return r

def get_latest_run(workflow_file):
    """Fetch the most recent run for this workflow"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/runs?branch={BRANCH}&per_page=1"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return None
    runs = r.json().get("workflow_runs", [])
    return runs[0] if runs else None

def get_run_jobs(run_id):
    """Fetch jobs for a run"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return []
    return r.json().get("jobs", [])

def get_job_logs(job_id):
    """Fetch logs for a specific job"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/jobs/{job_id}/logs"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return ""
    return r.text

def extract_pr_url(logs):
    """Extract first PR URL from job logs"""
    match = re.search(r"https://github\.com/[^\s]+/pull/\d+", logs)
    return match.group(0) if match else None

# ===================
# 🎨 Streamlit UI
# ===================
st.set_page_config(page_title="Blue-Green Deployment Panel", layout="wide")

# Custom CSS for cards
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

# Header
st.markdown(
    """
    <div style="text-align:center; padding:15px; background:linear-gradient(to right, #8e0e00, #b92b27); color:white; border-radius:12px;">
    <h1>🚀 Blue-Green Deployment Panel</h1>
    <p>Trigger autoswitch or test automation workflows for multiple services</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Workflow selector
st.markdown('<div class="card">', unsafe_allow_html=True)
workflow_choice = st.selectbox("Select Workflow", list(WORKFLOWS.keys()))
workflow_file = WORKFLOWS[workflow_choice]
st.markdown('</div>', unsafe_allow_html=True)

# Common apps list
apps = get_apps()

# ===================
# Workflow Inputs
# ===================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("⚙️ Workflow Inputs")

if workflow_choice == "Blue-Green Autoswitch":
    version = st.text_input("Version", value="1.0.0")

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

elif workflow_choice == "Blue-Green Test Automation":
    selectforautomation = st.checkbox("Select for Automation", value=False)
    selectrelease = st.selectbox("Release (Business Unit)", ["us", "uk", "eu", "apac"])
    selectenvironment = st.selectbox("Environment", ["dev", "qa", "int", "prod"])
    select_apps = st.multiselect("Services (Apps)", apps)
    selectrunstandby = st.checkbox("Run Standby", value=False)
st.markdown('</div>', unsafe_allow_html=True)

# ===================
# Trigger Workflow
# ===================
st.markdown('<div class="card">', unsafe_allow_html=True)
if st.button("🔥 Trigger Workflow(s)"):
    if workflow_choice == "Blue-Green Autoswitch":
        if not selected_apps:
            st.warning("⚠️ Please select at least one app")
        else:
            for app in selected_apps:
                inputs = {
                    "version": version,
                    "update_primary": str(update_primary).lower(),
                    "update_standy": str(update_standy).lower(),
                    "autoflip": str(autoflip).lower(),
                    "turnoffstandby": str(turnoffstandby).lower(),
                    "businessunit": businessunit,
                    "environment": environment,
                    "deployment_service": app,
                }
                st.write(f"📤 Sending inputs for **{app}**:", inputs)
                response = trigger_workflow(workflow_file, inputs)
                if response.status_code == 204:
                    st.success(f"✅ Workflow triggered for {app}")
                    time.sleep(3)
                    run = get_latest_run(workflow_file)
                    if run:
                        st.markdown(f"🔗 [View run for {app}]({run['html_url']})")
                        st.write(f"📊 Status: {run['status']}")
                        jobs = get_run_jobs(run["id"])
                        for job in jobs:
                            for step in job.get("steps", []):
                                if "PR" in step["name"] and step["conclusion"] == "success":
                                    logs = get_job_logs(job["id"])
                                    pr_url = extract_pr_url(logs)
                                    if pr_url:
                                        st.success(f"📎 PR Created: [Open PR]({pr_url})")
                                    else:
                                        st.info("ℹ️ PR created, but no URL found in logs")
                else:
                    st.error(f"❌ Failed for {app}: {response.status_code} - {response.text}")

    elif workflow_choice == "Blue-Green Test Automation":
        if not select_apps:
            st.warning("⚠️ Please select at least one app")
        else:
            for app in select_apps:
                inputs = {
                    "selectforautomation": str(selectforautomation).lower(),
                    "selectrelease": selectrelease,
                    "selectenvironment": selectenvironment,
                    "selectservice": app,
                    "selectrunstandby": str(selectrunstandby).lower(),
                }
                st.write(f"📤 Sending inputs for **{app}**:", inputs)
                response = trigger_workflow(workflow_file, inputs)
                if response.status_code == 204:
                    st.success(f"✅ Workflow triggered for {app}")
                    time.sleep(3)
                    run = get_latest_run(workflow_file)
                    if run:
                        st.markdown(f"🔗 [View run for {app}]({run['html_url']})")
                        st.write(f"📊 Status: {run['status']}")
                        jobs = get_run_jobs(run["id"])
                        for job in jobs:
                            for step in job.get("steps", []):
                                if "PR" in step["name"] and step["conclusion"] == "success":
                                    logs = get_job_logs(job["id"])
                                    pr_url = extract_pr_url(logs)
                                    if pr_url:
                                        st.success(f"📎 PR Created: [Open PR]({pr_url})")
                                    else:
                                        st.info("ℹ️ PR created, but no URL found in logs")
                else:
                    st.error(f"❌ Failed for {app}: {response.status_code} - {response.text}")
st.markdown('</div>', unsafe_allow_html=True)
