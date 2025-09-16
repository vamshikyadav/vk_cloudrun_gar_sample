# Project: Streamlit Blue/Green PR Orchestrator
# Files in this single document:
# - app.py (Streamlit app)
# - requirements.txt
# - Dockerfile
# - README.md

# =========================
# app.py
# =========================
# Project: Streamlit Blue/Green PR Orchestrator (case-insensitive appversion, weights & switches)

import base64
import io
import json
import os
import time
from datetime import datetime
from typing import Dict, Tuple, Optional

import requests
import streamlit as st
from ruamel.yaml import YAML

APP_TITLE = "Blue/Green Release Orchestrator"

# -------------- Utilities --------------

def _yaml_loader():
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y

def _now_slug():
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")

class GH:
    def __init__(self, token: str):
        self.token = token.strip()
        self.base = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _req(self, method: str, path: str, **kwargs):
        url = f"{self.base}{path}"
        r = requests.request(method, url, headers=self.headers, timeout=60, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub API error {r.status_code}: {r.text}")
        return r.json() if r.text else {}

    def get_default_branch(self, owner: str, repo: str) -> str:
        data = self._req("GET", f"/repos/{owner}/{repo}")
        return data.get("default_branch", "main")

    def get_branch_sha(self, owner: str, repo: str, branch: str) -> str:
        data = self._req("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        return data["object"]["sha"]

    def create_branch(self, owner: str, repo: str, new_branch: str, from_branch: str) -> None:
        base_sha = self.get_branch_sha(owner, repo, from_branch)
        self._req(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{new_branch}", "sha": base_sha},
        )

    def get_file(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> Dict:
        params = {"ref": ref} if ref else None
        return self._req("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)

    def update_file(self, owner: str, repo: str, path: str, message: str, new_content_bytes: bytes, branch: str, sha: str) -> Dict:
        b64 = base64.b64encode(new_content_bytes).decode("utf-8")
        return self._req(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path}",
            json={"message": message, "content": b64, "branch": branch, "sha": sha},
        )

    def create_pr(self, owner: str, repo: str, head: str, base: str, title: str, body: str = "") -> Dict:
        return self._req(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )

    def dispatch_workflow(self, owner: str, repo: str, workflow_file: str, ref: str, inputs: Optional[Dict] = None) -> Dict:
        return self._req(
            "POST",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches",
            json={"ref": ref, "inputs": inputs or {}},
        )

    def list_workflow_runs(self, owner: str, repo: str, workflow_file: str, branch: Optional[str] = None, per_page: int = 10) -> Dict:
        params = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        return self._req("GET", f"/repos/{owner}/{repo}/actions/workflows/{workflow_file}/runs", params=params)

# -------------- YAML helpers --------------

def _lower_keys(d: Dict):
    return {str(k).lower(): v for k, v in d.items()}

def _set_key_case_insensitive(d: Dict, key_options, value):
    opts = {str(k).lower() for k in key_options}
    for k in list(d.keys()):
        if str(k).lower() in opts:
            d[k] = value
            return
    d[next(iter(key_options))] = value

def detect_active_slot(doc: Dict) -> str:
    lk = _lower_keys(doc)
    blue = lk.get("blue", {})
    green = lk.get("green", {})
    if isinstance(blue, dict) and "activeslot" in _lower_keys(blue):
        return _lower_keys(blue)["activeslot"].strip().lower()
    if isinstance(green, dict) and "activeslot" in _lower_keys(green):
        return _lower_keys(green)["activeslot"].strip().lower()
    if "activeslot" in lk:
        return str(lk["activeslot"]).strip().lower()
    return "blue"

def set_active_slot_both(doc: Dict, slot: str) -> None:
    for section_name in ["blue", "green", "Blue", "Green"]:
        if section_name in doc and isinstance(doc[section_name], dict):
            _set_key_case_insensitive(doc[section_name], ["activeslot", "ActiveSlot"], slot)
    for sec in ["blue", "green", "Blue", "Green"]:
        if sec in doc and isinstance(doc[sec], dict):
            is_active = sec.lower() == slot.lower()
            _set_key_case_insensitive(doc[sec], ["Weight", "weight"], 100 if is_active else 0)
            _set_key_case_insensitive(doc[sec], ["Standbyweight", "standbyweight", "Standybyweight", "standybyweight"], 0 if is_active else 100)

def update_version(doc: Dict, slot: str, new_version: str) -> None:
    found = False
    for k in list(doc.keys()):
        lk = str(k).lower()
        if slot == "blue" and lk in ["appversion_blue", "appversionblue"]:
            doc[k] = new_version
            found = True
        if slot == "green" and lk in ["appversion_green", "appversiongreen"]:
            doc[k] = new_version
            found = True
    if not found:
        if slot == "blue":
            doc["Appversion_blue"] = new_version
        else:
            doc["Appversion_green"] = new_version

def standby_slot(active: str) -> str:
    return "green" if active == "blue" else "blue"

def turn_off_standby_switch(doc: Dict, standby: str):
    if standby == "blue":
        for sec in ["blue", "Blue"]:
            if sec in doc and isinstance(doc[sec], dict):
                _set_key_case_insensitive(doc[sec], ["blueswitch", "BlueSwitch"], "off")
    if standby == "green":
        for sec in ["green", "Green"]:
            if sec in doc and isinstance(doc[sec], dict):
                _set_key_case_insensitive(doc[sec], ["greenswitch", "GreenSwitch"], "off")

# -------------- PR builders --------------

def build_branch_name(app: str, env_label: str, action: str) -> str:
    app_slug = app.replace("/", "-")
    return f"feat/{app_slug}-{env_label}-{action}-{_now_slug()}"

def pr_title(app: str, env_label: str, action: str, version: Optional[str] = None) -> str:
    if version:
        return f"{app} [{env_label}] {action}: {version}"
    return f"{app} [{env_label}] {action}"

# -------------- Core ops --------------

def load_yaml_from_repo(gh: GH, owner: str, repo: str, path: str, ref: str) -> Tuple[Dict, str, bytes]:
    file_obj = gh.get_file(owner, repo, path, ref)
    sha = file_obj.get("sha")
    content_b64 = file_obj.get("content", "")
    content_bytes = base64.b64decode(content_b64)
    yaml_loader = _yaml_loader()
    data = yaml_loader.load(io.StringIO(content_bytes.decode("utf-8")))
    return data or {}, sha, content_bytes

def dump_yaml_to_bytes(doc: Dict) -> bytes:
    yaml_dumper = _yaml_loader()
    s = io.StringIO()
    yaml_dumper.dump(doc, s)
    return s.getvalue().encode("utf-8")

def propose_version_update(gh: GH, owner: str, repo: str, base_branch: str, yaml_path: str, app_label: str, env_label: str, target_slot: str, new_version: str) -> Dict:
    branch_name = build_branch_name(app_label, env_label, f"update-{target_slot}-version")
    gh.create_branch(owner, repo, branch_name, base_branch)
    doc, sha, _ = load_yaml_from_repo(gh, owner, repo, yaml_path, base_branch)
    update_version(doc, target_slot, new_version)
    new_bytes = dump_yaml_to_bytes(doc)
    commit_msg = f"chore({app_label}): bump {target_slot} version to {new_version} [{env_label}]"
    gh.update_file(owner, repo, yaml_path, commit_msg, new_bytes, branch_name, sha)
    title = pr_title(app_label, env_label, f"Update {target_slot} version", new_version)
    pr = gh.create_pr(owner, repo, head=branch_name, base=base_branch, title=title, body=f"Automated PR for {app_label} {env_label}")
    return {"branch": branch_name, "pr": pr}

def propose_auto_flip(gh: GH, owner: str, repo: str, base_branch: str, yaml_path: str, app_label: str, env_label: str, turn_off_switch: bool = False) -> Dict:
    branch_name = build_branch_name(app_label, env_label, "auto-flip")
    gh.create_branch(owner, repo, branch_name, base_branch)
    doc, sha, _ = load_yaml_from_repo(gh, owner, repo, yaml_path, base_branch)
    active = detect_active_slot(doc)
    target = standby_slot(active)
    set_active_slot_both(doc, target)
    if turn_off_switch:
        turn_off_standby_switch(doc, standby_slot(target))
    new_bytes = dump_yaml_to_bytes(doc)
    commit_msg = f"feat({app_label}): auto-flip active slot to {target} [{env_label}]"
    gh.update_file(owner, repo, yaml_path, commit_msg, new_bytes, branch_name, sha)
    title = pr_title(app_label, env_label, f"Auto flip to {target}")
    pr = gh.create_pr(owner, repo, head=branch_name, base=base_branch, title=title, body=f"Automated PR flipping active slot to {target}")
    return {"branch": branch_name, "pr": pr, "new_active": target}

# -------------- Streamlit UI --------------

def ui_header():
    st.title(APP_TITLE)
    st.caption("Generate PRs to update versions and flip blue/green slots. Cloud Run ready.")

def ui_sidebar() -> Dict:
    with st.sidebar:
        st.subheader("GitHub Settings")
        gh_token = st.text_input("GitHub Token", type="password")
        owner = st.text_input("Owner / Org", value="your-org")
        repo = st.text_input("Repository", value="your-repo")
        base_branch = st.text_input("Base branch", value="")
        app_label = st.text_input("App label", value="app1")
        yaml_path = st.text_input("YAML path", value="apps/app1/values-dev-us.yaml")
        workflow_file = st.text_input("Workflow filename", value="ci-tests.yml")
        workflow_ref = st.text_input("Workflow ref (branch/tag)", value="")
        return {"gh_token": gh_token, "owner": owner, "repo": repo, "base_branch": base_branch, "app_label": app_label, "yaml_path": yaml_path, "workflow_file": workflow_file, "workflow_ref": workflow_ref}

def ensure_gh(cfg: Dict) -> Tuple[GH, str]:
    if not cfg["gh_token"]:
        st.error("Please provide a GitHub token.")
        st.stop()
    gh = GH(cfg["gh_token"])
    base_branch = cfg["base_branch"] or gh.get_default_branch(cfg["owner"], cfg["repo"])
    return gh, base_branch

def section_nonprod(cfg: Dict):
    st.subheader("Non-Production")
    env_label = st.text_input("Env label", value="dev-us")
    action = st.radio("Update target", ["primary (active)", "standby"], index=1)
    new_version = st.text_input("Version to set", value="1.2.3")
    turn_off_req = st.checkbox("Turn off standby switch after flip (Non-Prod)", value=False)
    if st.button("Generate PR for version update", type="primary"):
        gh, base_branch = ensure_gh(cfg)
        doc, _, _ = load_yaml_from_repo(gh, cfg["owner"], cfg["repo"], cfg["yaml_path"], base_branch)
        active = detect_active_slot(doc)
        target = active if action.startswith("primary") else standby_slot(active)
        res = propose_version_update(gh, cfg["owner"], cfg["repo"], base_branch, cfg["yaml_path"], cfg["app_label"], env_label, target, new_version)
        pr = res["pr"]
        st.success("PR created!")
        st.write(f"**PR:** [{pr['title']}]({pr['html_url']})  ")

def section_prod(cfg: Dict):
    st.subheader("Production")
    env_label = st.text_input("Env label (prod variant)", value="prod-us")
    new_version = st.text_input("Standby version to set", value="2.0.0")
    trigger_tests = st.checkbox("Trigger GitHub Actions tests after PR", value=True)
    auto_flip_ready = st.checkbox("Enable Auto Flip step", value=True)
    turn_off_req = st.checkbox("Turn off standby switch after flip", value=False)
    inputs_raw = st.text_area("Workflow inputs (JSON)", value=json.dumps({"app": "app1", "env": "prod", "version": "2.0.0"}, indent=2), height=140)
    if st.button("Create PR to update STANDBY version", type="primary"):
        gh, base_branch = ensure_gh(cfg)
        doc, _, _ = load_yaml_from_repo(gh, cfg["owner"], cfg["repo"], cfg["yaml_path"], base_branch)
        active = detect_active_slot(doc)
        target = standby_slot(active)
        res = propose_version_update(gh, cfg["owner"], cfg["repo"], base_branch, cfg["yaml_path"], cfg["app_label"], env_label, target, new_version)
        pr = res["pr"]
        st.success("Standby update PR created!")
        st.write(f"**PR:** [{pr['title']}]({pr['html_url']})  ")
        if trigger_tests and cfg["workflow_file"]:
            inputs = json.loads(inputs_raw) if inputs_raw.strip() else {}
            ref = cfg["workflow_ref"] or cfg["base_branch"] or base_branch
            gh.dispatch_workflow(cfg["owner"], cfg["repo"], cfg["workflow_file"], ref, inputs)
            st.info("Workflow dispatched.")
    st.divider()
    st.markdown("### Auto Flip (after tests verified)")
    if auto_flip_ready and st.button("Create PR to AUTO FLIP active slot"):
        gh, base_branch = ensure_gh(cfg)
        res = propose_auto_flip(gh, cfg["owner"], cfg["repo"], base_branch, cfg["yaml_path"], cfg["app_label"], env_label, turn_off_switch=turn_off_req)
        pr = res["pr"]
        st.success(f"Auto-flip PR created! New active: {res['new_active']}")
        st.write(f"**PR:** [{pr['title']}]({pr['html_url']})  ")

def main():
    ui_header()
    cfg = ui_sidebar()
    tab1, tab2 = st.tabs(["Non-Prod", "Prod"])
    with tab1:
        section_nonprod(cfg)
    with tab2:
        section_prod(cfg)

if __name__ == "__main__":
    main()


# =========================
# requirements.txt
# =========================
# Streamlit UI
streamlit==1.37.0
# YAML preserving structure/quotes
ruamel.yaml==0.18.6
# HTTP
requests==2.32.3

# =========================
# Dockerfile
# =========================
# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./

# Streamlit listens on 8501 by default; Cloud Run provides $PORT
ENV PORT=8080
EXPOSE 8080

# Streamlit config for Cloud Run
CMD ["bash", "-lc", "streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --browser.gatherUsageStats=false"]

# =========================
# README.md
# =========================
# Blue/Green PR Orchestrator (Streamlit)

This Streamlit app lets you:

- Read an environment YAML (e.g., `values-dev-us.yaml`) per app
- Detect **active** blue/green slot
- Update **primary** (active) or **standby** slot version and open a PR
- In **production**: update the **standby** version, optionally **trigger tests** (workflow_dispatch), then **Auto Flip** the active slot and open a PR
- Designed to run on **Cloud Run**

## YAML expectations

Minimal example the app understands (case-insensitive for keys):

```yaml
Appversion_blue: "version1"
Appversion_green: "version2"

blue:
  blueswitch: "on"
  enabled: true
  activeslot: blue
  Weight: 100
  Standbyweight: 0

Green:
  greenswitch: "off"
  enabled: true
  activeslot: blue
  Weight: 100
  Standbyweight: 0
```

- The app reads `blue.activeslot` (or `green.activeslot`) to determine the **active** slot.
- **Update Standby** changes `Appversion_green` if active is blue, or `Appversion_blue` if active is green.
- **Auto Flip** sets `blue.activeslot` and `green.activeslot` to the standby slot so they match.

## GitHub token scopes

Create a token (classic PAT or fine-grained) with at least:

- `repo` (contents, pull requests)
- `workflow` (to trigger Actions)

Provide it in the sidebar when running locally; on Cloud Run, pass via `--set-env-vars` and read with `st.secrets` if desired.

## Local run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Container build & run

```bash
# Build
docker build -t bluegreen-orchestrator:latest .

# Run locally
docker run -p 8080:8080 \
  -e PORT=8080 \
  bluegreen-orchestrator:latest
```

Open http://localhost:8080

## Deploy to Cloud Run

```bash
gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/bluegreen-orchestrator

gcloud run deploy bluegreen-orchestrator \
  --image gcr.io/$(gcloud config get-value project)/bluegreen-orchestrator \
  --platform managed \
  --allow-unauthenticated \
  --region us-central1 \
  --set-env-vars PORT=8080
```

> Tip: Store your GitHub token as a Secret Manager secret and mount it as an env var:
>
> ```bash
> gcloud secrets create gh-token --data-file=<(echo -n YOUR_TOKEN)
> gcloud run services update bluegreen-orchestrator \
>   --update-secrets=GITHUB_TOKEN=gh-token:latest
> ```
>
> Then in `app.py`, replace `st.text_input("GitHub Token")` with reading `os.environ.get("GITHUB_TOKEN")` via `st.secrets` or environment.

## Workflow triggers

- Set **Workflow filename** to the YAML under `.github/workflows/`, e.g., `ci-tests.yml`.
- The app uses `workflow_dispatch` with custom `inputs` you supply as JSON.
- Use the **List recent workflow runs** button to get status links.

## Notes

- Branch names use `feat/<app>-<env>-<action>-<UTC timestamp>`.
- PR titles are descriptive and include app/env/action and version when applicable.
- YAML is updated with `ruamel.yaml` to preserve formatting/quotes where possible.
