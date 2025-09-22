import os
import re
import time
import json
import requests
import streamlit as st

# =========================
# 🔧 Configuration / Env
# =========================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
OWNER = os.getenv("GITHUB_OWNER", "your-org").strip()      # ← set or export GITHUB_OWNER
REPO  = os.getenv("GITHUB_REPO",  "your-repo").strip()     # ← set or export GITHUB_REPO
BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()        # ← set or export GITHUB_BRANCH

# Allow GitHub Enterprise (optional). Default is public GitHub.
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

WORKFLOWS = {
    "Blue-Green Autoswitch": "bluegreen.yaml",        # .github/workflows/bluegreen.yaml
    "Blue-Green Test Automation": "blue-green-test.yaml",  # .github/workflows/blue-green-test.yaml
}

# Common headers
def api_headers():
    token = GITHUB_TOKEN
    if not token:
        return {"Accept": "application/vnd.github.v3+json"}
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }

# =========================
# 🔗 GitHub API helpers
# =========================
def require_repo_config():
    errs = []
    if not OWNER or OWNER == "your-org":
        errs.append("OWNER is not set (set env GITHUB_OWNER or edit app.py).")
    if not REPO or REPO == "your-repo":
        errs.append("REPO is not set (set env GITHUB_REPO or edit app.py).")
    if not BRANCH:
        errs.append("BRANCH is not set (set env GITHUB_BRANCH or edit app.py).")
    return errs

def get_apps():
    """
    Fetch directories under helm-chart/ at a specific branch.
    Adds ?ref=<branch> so you always list from the right branch.
    """
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/contents/helm-chart?ref={BRANCH}"
    r = requests.get(url, headers=api_headers(), allow_redirects=True)
    if r.status_code == 404:
        raise RuntimeError(
            "404 from GitHub when listing helm-chart. "
            f"Checked URL: {url}\n"
            "• Verify OWNER/REPO are correct\n"
            "• Verify branch exists and you have access\n"
            "• Verify folder path is exactly 'helm-chart' (case & spelling)\n"
            "• If GitHub Enterprise, set GITHUB_API_URL"
        )
    r.raise_for_status()
    items = r.json()
    # Only return directories (apps)
    return [item["name"] for item in items if item.get("type") == "dir"]

def trigger_workflow(workflow_file, inputs):
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": BRANCH, "inputs": inputs}
    r = requests.post(url, headers=api_headers(), json=payload, allow_redirects=True)
    return r

def get_latest_run(workflow_file):
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/runs"
    params = {"branch": BRANCH, "event": "workflow_dispatch", "per_page": 5}
    r = requests.get(url, headers=api_headers(), params=params, allow_redirects=True)
    if r.status_code != 200:
        return None
    runs = r.json().get("workflow_runs", [])
    return runs[0] if runs else None

def get_run_jobs(run_id):
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs"
    r = requests.get(url, headers=api_headers(), allow_redirects=True)
    if r.status_code != 200:
        return []
    return r.json().get("jobs", [])

def get_job_logs(job_id):
    """
    Fetch logs for a specific job. GitHub returns a 302 to a signed URL; requests follows it.
    Content is text/plain; we return text for regex parsing.
    """
    url = f"{GITHUB_API_URL}/repos/{OWNER}/{REPO}/actions/jobs/{job_id}/logs"
    r = requests.get(url, headers=api_headers(), allow_redirects=True)
    if r.status_code != 200:
        return ""
    # logs can be bytes; ensure text
    try:
        return r.text
    except Exception:
        return r.content.decode("utf-8", errors="ignore")

def extract_pr_url(log_text):
    """
    Pull the first PR URL from logs. Example match:
    https://github.com/<owner>/<repo>/pull/123
    """
    m = re.search(r"https://github\.com/[^\s]+/pull/\d+", log_text)
    return m.group(0) if m else None

# =========================
# 🎨 Streamlit UI
# =========================
st.set_page_config(page_title="Blue-Green Deployment Panel", layout="wide")

# Matte red card style
st.markdown(
    """
    <style>
      body { background: #fff; }
      .card {
          background-color: #fbeaea;
          padding: 20px;
          border-radius: 12px;
          box-shadow: 2px 2px 10px rgba(0,0,0,0.10);
          margin-bottom: 20px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# Header
st.markdown(
    """
    <div style="text-align:center; padding:15px; background:linear-gradient(90deg,#8e0e00,#b92b27); color:white; border-radius:12px;">
      <h1>🚀 Blue-Green Deployment Panel</h1>
      <p>Trigger autoswitch or test automation for multiple services — with PR link extraction</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Config sanity
cfg_errs = require_repo_config()
if cfg_errs:
    st.error("Configuration errors:\n- " + "\n- ".join(cfg_errs))

# Workflow selector
st.markdown('<div class="card">', unsafe_allow_html=True)
workflow_choice = st.selectbox(
    "Select Workflow",
    list(WORKFLOWS.keys()),
    index=0
)
workflow_file = WORKFLOWS[workflow_choice]
st.caption(f"Workflow file: .github/workflows/{workflow_file} | Branch: {BRANCH}")
st.markdown('</div>', unsafe_allow_html=True)

# List apps from helm-chart at the selected branch
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("📦 Services from `helm-chart/`")
apps = []
apps_error = None
try:
    apps = get_apps()
except Exception as e:
    apps_error = str(e)

if apps_error:
    st.error(apps_error)
else:
    if not apps:
        st.warning("No apps found under `helm-chart/` on this branch.")
st.markdown('</div>', unsafe_allow_html=True)

# Inputs card
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
    environment  = st.selectbox("Environment",  ["dev", "qa", "int", "prod"])
    selected_apps = st.multiselect("Deployment Services (Apps)", apps)

elif workflow_choice == "Blue-Green Test Automation":
    selectforautomation = st.checkbox("Select for Automation", value=False)
    selectrelease      = st.selectbox("Release (Business Unit)", ["us", "uk", "eu", "apac"])
    selectenvironment  = st.selectbox("Environment", ["dev", "qa", "int", "prod"])
    selected_apps      = st.multiselect("Services (Apps)", apps)
    selectrunstandby   = st.checkbox("Run Standby", value=False)
st.markdown('</div>', unsafe_allow_html=True)

# Trigger + results
st.markdown('<div class="card">', unsafe_allow_html=True)
if st.button("🔥 Trigger Workflow(s)"):
    if not apps or not selected_apps:
        st.warning("⚠️ Please ensure apps are listed and at least one app is selected.")
    else:
        # Trigger one run per selected app
        for app in selected_apps:
            if workflow_choice == "Blue-Green Autoswitch":
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
            else:  # Blue-Green Test Automation
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

            st.success(f"✅ Triggered workflow for {app}")
            # Small delay so the run appears in list
            time.sleep(3)

            run = get_latest_run(workflow_file)
            if not run:
                st.warning("Could not locate the new run yet. Check Actions UI.")
                continue

            run_url = run.get("html_url")
            run_id  = run.get("id")
            st.markdown(f"🔗 [View run for {app}]({run_url})")
            st.write(f"📊 Status: {run.get('status')} | Conclusion: {run.get('conclusion')}")

            # Try to find PR link by scanning 'Create PR' job logs
            jobs = get_run_jobs(run_id)
            pr_shown = False
            for job in jobs:
                for step in job.get("steps", []):
                    name = step.get("name", "")
                    if "PR" in name or "Create PR" in name:
                        # Only check logs if the step finished (success or failure)
                        if step.get("status") in ("completed",) and step.get("conclusion") == "success":
                            logs = get_job_logs(job["id"])
                            pr_url = extract_pr_url(logs)
                            if pr_url:
                                st.success(f"📎 PR Created: [Open PR]({pr_url})")
                                pr_shown = True
                                break
                if pr_shown:
                    break

            if not pr_shown:
                st.info("ℹ️ No PR URL found yet. It may appear after logs finish uploading.")
st.markdown('</div>', unsafe_allow_html=True)

# (Optional) simple debug toggle
with st.expander("🔍 Debug"):
    st.code(json.dumps({
        "owner": OWNER, "repo": REPO, "branch": BRANCH,
        "api_base": GITHUB_API_URL,
        "workflows": WORKFLOWS
    }, indent=2))