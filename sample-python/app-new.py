import os
import re
import json
import requests
import streamlit as st
from typing import Dict, List

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
    "Blue-Green Container": "blue-green-container.yaml",
}

def api_headers() -> Dict[str, str]:
    base = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        base["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return base

# ===================
# 🛠 Helpers (GitHub)
# ===================
def require_repo_config() -> List[str]:
    errs = []
    if not OWNER or OWNER == "your-org":
        errs.append("OWNER is not set (env GITHUB_OWNER).")
    if not REPO or REPO == "your-repo":
        errs.append("REPO is not set (env GITHUB_REPO).")
    if not BRANCH:
        errs.append("BRANCH is not set (env GITHUB_BRANCH).")
    return errs

def get_apps() -> List[str]:
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/contents/helm-chart?ref={BRANCH}"
    r = requests.get(url, headers=api_headers())
    r.raise_for_status()
    return [item["name"] for item in r.json() if item.get("type") == "dir"]

def trigger_workflow(workflow_file: str, inputs: Dict[str, str]) -> requests.Response:
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": BRANCH, "inputs": inputs}
    return requests.post(url, headers=api_headers(), json=payload)

# ===================
# 🎨 Streamlit UI
# ===================
st.set_page_config(page_title="Blue-Green Deployment Panel", layout="wide")

# Matte gray style + flashy logo + dropdown outline
st.markdown(
    """
    <style>
      .stApp { background: #f3f4f6; }
      .card {
          background-color: #ffffff;
          padding: 20px;
          border-radius: 16px;
          box-shadow: 2px 2px 14px rgba(0,0,0,0.10);
          margin-bottom: 20px;
          border: 1px solid #e5e7eb;
      }
      .logo-text {
          font-weight: 800;
          font-size: 42px;
          background: linear-gradient(90deg,#ff512f,#f09819,#ff512f);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          animation: hue 6s infinite linear;
          margin: 0;
      }
      @keyframes hue { 0% { filter: hue-rotate(0deg); } 100% { filter: hue-rotate(360deg); } }
      .stButton>button {
          background: linear-gradient(90deg,#111827,#1f2937);
          color: white;
          border: 0;
          padding: 0.6rem 1.1rem;
          border-radius: 12px;
          box-shadow: 0 8px 20px rgba(0,0,0,0.2);
      }
      .stButton>button:hover {
          transform: translateY(-1px);
          box-shadow: 0 10px 24px rgba(0,0,0,0.25);
      }
      /* dropdown outline */
      div[data-baseweb="select"] > div {
          border: 2px solid #374151 !important;
          border-radius: 8px !important;
          box-shadow: 0 1px 4px rgba(0,0,0,0.08);
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# Header
st.markdown(
    """
    <div style="text-align:center; padding:18px; background:#ffffff; border:1px solid #e5e7eb; border-radius:16px; box-shadow: 2px 2px 14px rgba(0,0,0,0.08); margin-bottom: 16px;">
      <h1 class="logo-text">Blue-Green Control Center</h1>
      <div class="subtitle">Trigger autoswitch, container, or test automation — per-service versions & PR links</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# State
if "tracked_runs" not in st.session_state:
    st.session_state["tracked_runs"] = []

# Config sanity
cfg_errs = require_repo_config()
if cfg_errs:
    st.error("Configuration errors:\n- " + "\n- ".join(cfg_errs))

# Workflow choice
st.markdown('<div class="card">', unsafe_allow_html=True)
workflow_choice = st.selectbox("Select Workflow", list(WORKFLOWS.keys()))
workflow_file = WORKFLOWS[workflow_choice]
st.caption(f"Workflow file: .github/workflows/{workflow_file} • Branch: {BRANCH}")
st.markdown('</div>', unsafe_allow_html=True)

# Services
apps = []
try:
    apps = get_apps()
except Exception as e:
    st.error(str(e))

# Inputs
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("⚙️ Workflow Inputs")

selected_apps = []
versions = {}

if workflow_choice == "Blue-Green Autoswitch":
    col1, col2 = st.columns(2)
    with col1:
        update_primary = st.checkbox("Update Primary", value=False)
        update_standy  = st.checkbox("Update Standby", value=False)
    with col2:
        autoflip       = st.checkbox("Auto Flip", value=False)
        turnoffstandby = st.checkbox("Turn Off Standby", value=False)
        turnonstandby  = st.checkbox("Turn On Standby", value=False)

    businessunit = st.selectbox("Business Unit", ["us", "uk", "eu", "apac"])
    environment  = st.selectbox("Environment",  ["dev", "qa", "int", "prod"])

    selected_apps = st.multiselect("Deployment Services (Apps)", apps)
    if selected_apps:
        st.write("### Per-App Versions")
        for app in selected_apps:
            versions[app] = st.text_input(f"Version for {app}", value="1.0.0")

elif workflow_choice == "Blue-Green Test Automation":
    test_automation = st.checkbox("Test Automation", value=False)
    businessunit    = st.selectbox("Business Unit", ["us", "uk", "ca"])
    environment     = st.selectbox("Environment", ["dev", "qa", "int"])
    selected_apps   = st.multiselect("Deployment Services (Apps)", apps)
    standby         = st.checkbox("Standby", value=False)
    version         = st.text_input("Version", value="1.0.0")

elif workflow_choice == "Blue-Green Container":
    col1, col2 = st.columns(2)
    with col1:
        update_primary = st.checkbox("Update Primary", value=False)
        update_standy  = st.checkbox("Update Standby", value=False)
    with col2:
        autoflip       = st.checkbox("Auto Flip", value=False)
        turnoffstandby = st.checkbox("Turn Off Standby", value=False)
        turnonstandby  = st.checkbox("Turn On Standby", value=False)

    businessunit = st.selectbox("Business Unit", ["us", "uk", "eu", "apac"])
    environment  = st.selectbox("Environment",  ["dev", "qa", "int", "prod"])

    selected_apps = st.multiselect("Deployment Services (Apps)", apps)
    if selected_apps:
        st.write("### Per-App Versions")
        for app in selected_apps:
            versions[app] = st.text_input(f"Version for {app}", value="1.0.0")

st.markdown('</div>', unsafe_allow_html=True)

# Trigger
st.markdown('<div class="card">', unsafe_allow_html=True)
if st.button("🔥 Trigger Workflow(s)"):
    if not selected_apps:
        st.warning("⚠️ Please select at least one app")
    else:
        for app in selected_apps:
            if workflow_choice == "Blue-Green Autoswitch":
                inputs = {
                    "version": versions.get(app, "1.0.0"),
                    "update_primary": str(update_primary).lower(),
                    "update_standy": str(update_standy).lower(),
                    "autoflip": str(autoflip).lower(),
                    "turnoffstandby": str(turnoffstandby).lower(),
                    "turnonstandby": str(turnonstandby).lower(),
                    "businessunit": businessunit,
                    "environment": environment,
                    "deployment_service": app,
                }

            elif workflow_choice == "Blue-Green Test Automation":
                inputs = {
                    "test_automation": str(test_automation).lower(),
                    "businessunit": businessunit,
                    "environment": environment,
                    "deploymentservice": app,  # match YAML
                    "standby": str(standby).lower(),
                    "version": version,
                }

            elif workflow_choice == "Blue-Green Container":
                inputs = {
                    "version": versions.get(app, "1.0.0"),
                    "update_primary": str(update_primary).lower(),
                    "update_standy": str(update_standy).lower(),
                    "autoflip": str(autoflip).lower(),
                    "turnoffstandby": str(turnoffstandby).lower(),
                    "turnonstandby": str(turnonstandby).lower(),
                    "businessunit": businessunit,
                    "environment": environment,
                    "deployment_service": app,
                }

            st.write(f"📤 Sending inputs for **{app}**:", inputs)
            resp = trigger_workflow(workflow_file, inputs)
            if resp.status_code != 204:
                st.error(f"❌ Failed for {app}: {resp.status_code} - {resp.text}")
            else:
                st.success(f"✅ Workflow triggered for {app}")
                st.session_state["tracked_runs"].append({
                    "app": app,
                    "workflow": workflow_choice,
                    "inputs": inputs
                })
st.markdown('</div>', unsafe_allow_html=True)

# Refresh & Tracked Runs
st.markdown('<div class="card">', unsafe_allow_html=True)
if st.button("🔄 Refresh Status"):
    if not st.session_state["tracked_runs"]:
        st.info("No runs tracked yet.")
    else:
        st.subheader("📜 Tracked Workflow Runs")
        for run in st.session_state["tracked_runs"]:
            st.write(f"**App:** {run['app']} | **Workflow:** {run['workflow']}")
            st.json(run["inputs"])
st.markdown('</div>', unsafe_allow_html=True)
