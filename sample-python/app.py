import os
import streamlit as st
import yaml
from github import Github
import requests
from dotenv import load_dotenv

# --- Load .env if present ---
load_dotenv()

# --- ENVIRONMENT VARIABLES ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")  # e.g. "your-org/your-repo"
HELM_CHART_DIR = "helm-chart"

if not GITHUB_TOKEN or not REPO_NAME:
    st.error("❌ Missing required env vars: GITHUB_TOKEN and REPO_NAME")
    st.stop()

# --- GITHUB CLIENT ---
g = Github(GITHUB_TOKEN)
repo = g.get_repo(REPO_NAME)

# --- STYLE + LOGO ---
st.set_page_config(page_title="Helm Ops Console", page_icon="⚡", layout="wide")

st.markdown(
    """
    <style>
    .top-bar {
        display: flex;
        align-items: center;
        justify-content: left;
        background: linear-gradient(90deg, #141e30, #243b55);
        padding: 10px 20px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    .top-bar img {
        height: 50px;
        margin-right: 15px;
    }
    .top-bar h1 {
        color: white;
        font-size: 28px;
        margin: 0;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(
    """
    <div class="top-bar">
        <img src="https://img.icons8.com/external-flaticons-flat-flat-icons/64/ffffff/external-rocket-startup-flaticons-flat-flat-icons.png" />
        <h1>Helm Chart Operations Console 🚀</h1>
    </div>
    """,
    unsafe_allow_html=True
)

# --- STREAMLIT UI ---
st.subheader("Application & Environment Selection")

# Step 1: Select applications
apps = [d.name for d in repo.get_contents(HELM_CHART_DIR) if d.type == "dir"]
selected_apps = st.multiselect("📦 Select Applications", apps)

# Step 2: Select environment & region
col1, col2 = st.columns(2)
with col1:
    env = st.selectbox("🌍 Select Environment", ["dev", "qa", "prod"])
with col2:
    region = st.selectbox("📡 Select Region", ["us", "eu", "apac"])

# Step 3: Choose operation
st.subheader("Operations")
operation = st.radio("⚙️ Choose Operation", [
    "Update Primary",
    "Update Standby",
    "Autoflip",
    "Turn off Standby"
])

# Step 4: Workflow trigger (only for standby/autoflip)
workflow_name = None
workflow_param = None
if operation in ["Update Standby", "Autoflip"]:
    st.subheader("Workflow Trigger")
    workflow_name = st.text_input("Workflow Name (GitHub Actions)")
    workflow_param = st.text_input("Workflow Parameter")

# --- YAML Update Logic ---
def update_yaml(file_content, operation, new_version):
    data = yaml.safe_load(file_content)

    blue_active = data.get("blue", {}).get("activeSlot")
    green_active = data.get("green", {}).get("activeSlot")

    if operation == "Update Primary":
        if blue_active == "blue":
            data["appversion_blue"] = new_version
        else:
            data["appversion_green"] = new_version

    elif operation == "Update Standby":
        if blue_active == "blue":
            data["appversion_green"] = new_version
        else:
            data["appversion_blue"] = new_version

    elif operation == "Autoflip":
        if blue_active == "blue":
            data["blue"].update({
                "blueswitch": "on", "enabled": True,
                "activeSlot": "green", "weight": 0, "standbyWeight": 100
            })
            data["green"].update({
                "blueswitch": "on", "enabled": True,
                "activeSlot": "green", "weight": 100, "standbyWeight": 0
            })
        else:
            data["blue"].update({
                "blueswitch": "on", "enabled": True,
                "activeSlot": "blue", "weight": 100, "standbyWeight": 0
            })
            data["green"].update({
                "blueswitch": "on", "enabled": True,
                "activeSlot": "blue", "weight": 0, "standbyWeight": 100
            })

    elif operation == "Turn off Standby":
        if blue_active == "blue":
            data["green"]["blueswitch"] = "off"
        else:
            data["blue"]["blueswitch"] = "off"

    return yaml.dump(data, sort_keys=False)

# --- Submit ---
st.subheader("Execution")
new_version = st.text_input("Enter New Version (if applicable)", "new-version")

if st.button("🚀 Submit Changes"):
    for app in selected_apps:
        file_path = f"{HELM_CHART_DIR}/{app}/values-{env}-{region}.yaml"
        file = repo.get_contents(file_path)
        updated_yaml = update_yaml(file.decoded_content.decode(), operation, new_version)

        branch = f"{app}-{operation.lower()}-update"
        base = repo.get_branch("main")
        try:
            repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base.commit.sha)
        except Exception:
            st.warning(f"⚠️ Branch {branch} already exists, using it...")

        repo.update_file(
            path=file_path,
            message=f"[Streamlit] {operation} update for {app}",
            content=updated_yaml,
            sha=file.sha,
            branch=branch
        )

        pr = repo.create_pull(
            title=f"{operation} update for {app}",
            body="Automated update via Streamlit app",
            head=branch,
            base="main"
        )
        st.success(f"✅ PR created: {pr.html_url}")

        if workflow_name and workflow_param:
            url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/{workflow_name}/dispatches"
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            payload = {"ref": "main", "inputs": {"param": workflow_param}}
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 204:
                st.info(f"🚀 Workflow {workflow_name} triggered with param `{workflow_param}`")
            else:
                st.error(f"❌ Failed to trigger workflow: {resp.text}")
