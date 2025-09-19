import streamlit as st
import requests
import os
import json
import time

# ===================
# 🔑 GitHub settings
# ===================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # export before running
OWNER = "your-org"
REPO = "your-repo"
BRANCH = "main"

headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# ===================
# 📝 Utility functions
# ===================
def get_apps():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/helm-chart"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return [item["name"] for item in resp.json() if item["type"] == "dir"]

def get_workflows():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()["workflows"]

def trigger_workflow(workflow_filename, app_versions):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{workflow_filename}/dispatches"
    payload = {
        "ref": BRANCH,
        "inputs": {
            "app_versions": json.dumps(app_versions)  # proper JSON string
        }
    }
    r = requests.post(url, headers=headers, json=payload)
    return r

def get_latest_run(workflow_filename):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{workflow_filename}/runs?branch={BRANCH}&per_page=1"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return None
    runs = r.json().get("workflow_runs", [])
    return runs[0] if runs else None

# ===================
# 🎨 Streamlit UI
# ===================
st.set_page_config(page_title="Blue-Green Control Panel", layout="wide")

# Operations log
log_container = st.container()
with log_container:
    st.subheader("📜 Operations Log")

# Flashy header
st.markdown(
    """
    <div style="text-align:center; padding:15px; background:linear-gradient(to right, #0f2027, #203a43, #2c5364); color:white; border-radius:12px;">
    <h1>🚀 Blue-Green Deployment Panel</h1>
    <p>Select apps, enter versions, trigger workflows & track status</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Workflow selection
workflows = get_workflows()
workflow_map = {wf["name"]: wf["path"].split("/")[-1] for wf in workflows if "Blue-Green" in wf["name"]}
workflow_choice = st.selectbox("Select Workflow", list(workflow_map.keys()))
workflow_file = workflow_map[workflow_choice]

with log_container:
    st.info(f"Loaded workflow: {workflow_choice} ({workflow_file})")

# Apps list
apps = get_apps()
selected_apps = st.multiselect("Select apps to deploy", apps)

# Versions
app_versions = {}
cols = st.columns(2)
for idx, app in enumerate(selected_apps):
    with cols[idx % 2]:
        version = st.text_input(f"Version for {app}", value="1.0.0")
        app_versions[app] = version

# Trigger button
if st.button("🔥 Trigger Workflow"):
    with log_container:
        st.write("Triggering workflow…")
    response = trigger_workflow(workflow_file, app_versions)
    if response.status_code == 204:
        with log_container:
            st.success(f"✅ {workflow_choice} triggered for {len(app_versions)} apps")

        # Fetch and display status
        st.write("🔄 Fetching workflow run status...")
        time.sleep(3)  # short wait for GitHub to register run
        run = get_latest_run(workflow_file)
        if run:
            run_url = run["html_url"]
            st.markdown(f"🔗 [View run on GitHub]({run_url})")

            with st.empty():
                while True:
                    run = get_latest_run(workflow_file)
                    if not run:
                        st.error("❌ Could not fetch run status.")
                        break
                    status = run["status"]
                    conclusion = run.get("conclusion")
                    st.write(f"📊 Status: **{status}**")
                    if conclusion:
                        st.write(f"✅ Conclusion: **{conclusion}**")
                        break
                    time.sleep(10)  # refresh every 10s
        else:
            st.error("❌ No recent run found.")
    else:
        with log_container:
            st.error(f"❌ Failed: {response.status_code} - {response.text}")
