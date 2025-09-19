import streamlit as st
import requests
import os
import json
import time
import yaml

# ===================
# 🔑 GitHub settings
# ===================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()  # strip fixes newline issue
OWNER = "your-org"   # 🔥 change me
REPO = "your-repo"   # 🔥 change me
BRANCH = "main"

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

def get_workflows():
    """Fetch workflows in repo"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()["workflows"]

def get_workflow_yaml(workflow_path):
    """Fetch workflow YAML definition"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{workflow_path}"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    download_url = r.json()["download_url"]
    yaml_text = requests.get(download_url).text
    return yaml.safe_load(yaml_text)

def trigger_workflow(workflow_filename, inputs):
    """Trigger workflow_dispatch"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{workflow_filename}/dispatches"
    payload = {"ref": BRANCH, "inputs": inputs}
    r = requests.post(url, headers=headers, json=payload)
    return r

def get_latest_runs(workflow_filename, limit=3):
    """Fetch latest workflow runs"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{workflow_filename}/runs?branch={BRANCH}&per_page={limit}"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return []
    return r.json().get("workflow_runs", [])

def get_run_jobs(run_id):
    """Fetch jobs for a run"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return []
    return r.json().get("jobs", [])

# ===================
# 🎨 Streamlit UI
# ===================
st.set_page_config(page_title="Blue-Green Deployment Panel", layout="wide")

log_container = st.container()
with log_container:
    st.subheader("📜 Operations Log")

# Header
st.markdown(
    """
    <div style="text-align:center; padding:15px; background:linear-gradient(to right, #1e3c72, #2a5298); color:white; border-radius:12px;">
    <h1>🚀 Blue-Green Deployment Panel</h1>
    <p>Trigger multiple workflows, track runs, and capture PRs</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Workflow selector
workflows = get_workflows()
workflow_map = {wf["name"]: wf["path"] for wf in workflows if "Blue-Green" in wf["name"]}
workflow_choice = st.selectbox("Select Workflow", list(workflow_map.keys()))
workflow_file = workflow_map[workflow_choice]

with log_container:
    st.info(f"Loaded workflow: {workflow_choice} ({workflow_file})")

# Load apps from repo
apps = get_apps()
selected_apps = st.multiselect("Select apps to deploy", apps)

# Collect app versions
app_versions = {}
cols = st.columns(2)
for idx, app in enumerate(selected_apps):
    with cols[idx % 2]:
        version = st.text_input(f"Version for {app}", value="1.0.0")
        app_versions[app] = version

# Optional: parse workflow_dispatch inputs from YAML (fallback if no apps)
workflow_yaml = get_workflow_yaml(workflow_file)
inputs_schema = workflow_yaml.get("on", {}).get("workflow_dispatch", {}).get("inputs", {})

if not selected_apps and inputs_schema:
    st.write("### Other Workflow Parameters")
    for key, meta in inputs_schema.items():
        default = meta.get("default", "")
        desc = meta.get("description", key)
        user_val = st.text_input(f"{desc} ({key})", value=default)
        app_versions[key] = user_val

# Trigger workflow
if st.button("🔥 Trigger Workflow"):
    with log_container:
        st.info(f"Triggering {workflow_choice}...")
    inputs = {"app_versions": json.dumps(app_versions)} if selected_apps else app_versions
    response = trigger_workflow(workflow_file.split("/")[-1], inputs)
    if response.status_code == 204:
        st.success("✅ Triggered successfully")
        time.sleep(3)
        runs = get_latest_runs(workflow_file.split("/")[-1])
        for run in runs:
            st.session_state.setdefault("tracked_runs", []).append(run)
    else:
        st.error(f"❌ Failed: {response.status_code} - {response.text}")

# Display tracked runs
if "tracked_runs" in st.session_state:
    st.write("### Tracked Workflow Runs")
    for run in st.session_state["tracked_runs"]:
        run_id = run["id"]
        st.markdown(f"🔗 [{run['name']} #{run['run_number']}]({run['html_url']})")
        st.write(f"📊 Status: {run['status']} | Conclusion: {run.get('conclusion')}")

        jobs = get_run_jobs(run_id)
        for job in jobs:
            for step in job.get("steps", []):
                if "Create PR" in step["name"] and step["conclusion"] == "success":
                    st.success(f"✅ PR created in job {job['name']}")
