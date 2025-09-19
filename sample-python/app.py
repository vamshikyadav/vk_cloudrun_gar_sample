import streamlit as st
import requests
import os
import json
import time

# ===================
# 🔑 GitHub settings
# ===================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
OWNER = "your-org"   # 🔥 change me
REPO = "your-repo"   # 🔥 change me
BRANCH = "main"
WORKFLOW_FILE = "bluegreen.yaml"   # matches .github/workflows/bluegreen.yaml

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

def trigger_workflow(inputs):
    """Trigger workflow_dispatch"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    payload = {"ref": BRANCH, "inputs": inputs}
    r = requests.post(url, headers=headers, json=payload)
    return r

def get_latest_run():
    """Fetch the most recent run for this workflow"""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs?branch={BRANCH}&per_page=1"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return None
    runs = r.json().get("workflow_runs", [])
    return runs[0] if runs else None

# ===================
# 🎨 Streamlit UI
# ===================
st.set_page_config(page_title="Blue-Green Autoswitch Panel", layout="wide")

# Custom CSS
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
    <h1>🚀 Blue-Green Autoswitch</h1>
    <p>Trigger blue-green deployments for multiple services</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Inputs card
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("⚙️ Workflow Inputs")

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

apps = get_apps()
selected_apps = st.multiselect("Deployment Services (Apps)", apps)
st.markdown('</div>', unsafe_allow_html=True)

# Trigger block
st.markdown('<div class="card">', unsafe_allow_html=True)
if st.button("🔥 Trigger Workflow(s)"):
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

            response = trigger_workflow(inputs)
            if response.status_code == 204:
                st.success(f"✅ Workflow triggered for {app}")
                time.sleep(2)  # let GitHub register the run
                run = get_latest_run()
                if run:
                    st.markdown(f"🔗 [View run for {app}]({run['html_url']})")
                    st.write(f"📊 Status: {run['status']}")
            else:
                st.error(f"❌ Failed for {app}: {response.status_code} - {response.text}")
st.markdown('</div>', unsafe_allow_html=True)
