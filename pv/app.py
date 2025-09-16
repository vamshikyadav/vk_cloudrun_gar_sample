# Project: Streamlit Blue/Green PR Orchestrator (case-insensitive appversion, weights & switches)
import base64
import io
import json
import os
from datetime import datetime
from typing import Dict, Tuple, Optional

import requests
import streamlit as st
from ruamel.yaml import YAML

st.set_page_config(page_title="Operations · Blue/Green Orchestrator", page_icon="🛠️", layout="wide")

APP_TITLE = "Blue/Green Release Orchestrator · Operations"

# -------------- Utilities --------------

APP_ROOT_DEFAULT = os.environ.get("APPS_ROOT", "apps")

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

    def update_file(
        self, owner: str, repo: str, path: str, message: str, new_content_bytes: bytes, branch: str, sha: str
    ) -> Dict:
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
    """
    Write to any existing key among key_options (case-insensitive). If none exist,
    create the first preferred key to avoid duplicate keys with different casing.
    """
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
    # set activeslot for both sections (case-insensitive write)
    for section_name in ["blue", "green", "Blue", "Green"]:
        if section_name in doc and isinstance(doc[section_name], dict):
            _set_key_case_insensitive(doc[section_name], ["activeslot", "ActiveSlot"], slot)
    # enforce weights: primary(active) 100/0; standby 0/100 (case-insensitive write)
    for sec in ["blue", "green", "Blue", "Green"]:
        if sec in doc and isinstance(doc[sec], dict):
            is_active = sec.lower() == slot.lower()
            _set_key_case_insensitive(doc[sec], ["Weight", "weight"], 100 if is_active else 0)
            _set_key_case_insensitive(
                doc[sec],
                ["Standbyweight", "standbyweight", "Standybyweight", "standybyweight"],
                0 if is_active else 100,
            )

def update_version(doc: Dict, slot: str, new_version: str) -> None:
    """
    Update Appversion_blue/Appversion_green in a case-insensitive way.
    Accept both 'appversion_blue' and 'appversionblue' style keys.
    """
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
    # turn OFF the standby's switch key (case-insensitive write)
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

def list_dir_contents(gh: GH, owner: str, repo: str, path: str, ref: str) -> list:
    try:
        items = gh.get_file(owner, repo, path, ref)
        return items if isinstance(items, list) else []
    except Exception:
        return []

def list_apps(gh: GH, owner: str, repo: str, base_path: str, ref: str) -> list:
    apps = []
    for item in list_dir_contents(gh, owner, repo, base_path, ref):
        if item.get("type") == "dir":
            apps.append(item.get("name"))
    return sorted(apps)

def list_value_files(gh: GH, owner: str, repo: str, app_folder: str, base_path: str, ref: str) -> list:
    values = []
    for item in list_dir_contents(gh, owner, repo, f"{base_path}/{app_folder}", ref):
        if item.get("type") == "file":
            name = item.get("name", "")
            if name.lower().startswith("values") and name.lower().endswith((".yaml", ".yml")):
                values.append(name)
    return sorted(values)

def propose_version_update(
    gh: GH,
    owner: str,
    repo: str,
    base_branch: str,
    yaml_path: str,
    app_label: str,
    env_label: str,
    target_slot: str,
    new_version: str,
) -> Dict:
    branch_name = build_branch_name(app_label, env_label, f"update-{target_slot}-version")
    gh.create_branch(owner, repo, branch_name, base_branch)

    doc, sha, _ = load_yaml_from_repo(gh, owner, repo, yaml_path, base_branch)
    update_version(doc, target_slot, new_version)

    new_bytes = dump_yaml_to_bytes(doc)
    commit_msg = f"chore({app_label}): bump {target_slot} version to {new_version} [{env_label}]"
    gh.update_file(owner, repo, yaml_path, commit_msg, new_bytes, branch_name, sha)

    title = pr_title(app_label, env_label, f"Update {target_slot} version", new_version)
    body = (
        f"Automated PR via Streamlit app.\\n\\n"
        f"**App:** {app_label}\\n\\n**Env:** {env_label}\\n\\n**Target slot:** {target_slot}\\n\\n**New version:** {new_version}\\n"
    )
    pr = gh.create_pr(owner, repo, head=branch_name, base=base_branch, title=title, body=body)
    return {"branch": branch_name, "pr": pr}

def propose_auto_flip(
    gh: GH,
    owner: str,
    repo: str,
    base_branch: str,
    yaml_path: str,
    app_label: str,
    env_label: str,
    turn_off_switch: bool = False,
) -> Dict:
    branch_name = build_branch_name(app_label, env_label, "auto-flip")
    gh.create_branch(owner, repo, branch_name, base_branch)

    doc, sha, _ = load_yaml_from_repo(gh, owner, repo, yaml_path, base_branch)
    active = detect_active_slot(doc)
    target = standby_slot(active)

    # Flip activeslot (both sections), update weights accordingly
    set_active_slot_both(doc, target)

    # Optionally turn OFF standby switch
    if turn_off_switch:
        turn_off_standby_switch(doc, standby_slot(target))

    new_bytes = dump_yaml_to_bytes(doc)
    commit_msg = f"feat({app_label}): auto-flip active slot to {target} [{env_label}]"
    gh.update_file(owner, repo, yaml_path, commit_msg, new_bytes, branch_name, sha)

    title = pr_title(app_label, env_label, f"Auto flip to {target}")
    body = (
        f"Automated PR to flip activeslot and adjust weights.\\n\\n"
        f"**App:** {app_label}\\n\\n**Env:** {env_label}\\n\\n**New active slot:** {target}\\n"
        + ("Standby switch turned OFF.\\n" if turn_off_switch else "")
    )
    pr = gh.create_pr(owner, repo, head=branch_name, base=base_branch, title=title, body=body)
    return {"branch": branch_name, "pr": pr, "new_active": target}

# -------------- Streamlit UI --------------

def ui_header():
    # Fancy Operations logo badge + subtle gradient
    st.markdown(
        """
        <style>
        .ops-logo { font-weight: 800; font-size: 18px; letter-spacing: 2px;
            padding: 6px 10px; border-radius: 12px; display:inline-block;
            background: linear-gradient(90deg, #0ea5e9, #22c55e, #a78bfa);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .ops-chip { padding: 2px 8px; border-radius: 999px; font-size: 10px;
            background: linear-gradient(90deg, rgba(14,165,233,.15), rgba(34,197,94,.15), rgba(167,139,250,.15));
            color: #0ea5e9; border: 1px solid rgba(14,165,233,.35); margin-left: 8px;
        }
        </style>
        <div style="display:flex; align-items:center; gap:8px;">
          <div class="ops-logo">OPERATIONS</div>
          <div class="ops-chip">blue/green • PRs • Actions</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.title(APP_TITLE)
    st.caption("Generate PRs to update versions and flip blue/green slots. Cloud Run ready.")

def ui_sidebar() -> Dict:
    with st.sidebar:
        st.subheader("GitHub Settings")

        # Token: allow env var default so you can hide input in Cloud Run
        gh_token = st.text_input("GitHub Token", type="password", value=os.environ.get("GITHUB_TOKEN", ""))

        # Owner/repo defaults from env (override in UI if needed)
        owner = st.text_input("Owner / Org", value=os.environ.get("GH_OWNER", "your-org"))
        repo = st.text_input("Repository", value=os.environ.get("GH_REPO", "your-repo"))
        base_branch = st.text_input("Base branch", value=os.environ.get("GH_BRANCH", ""))

        st.divider()
        st.subheader("Repo Paths & Discovery")
        base_path = st.text_input("Apps base path", value=APP_ROOT_DEFAULT, help="Parent folder that contains app folders")

        # Discover apps & value files dynamically
        discovered_apps = []
        discovered_values = []
        try:
            if gh_token and owner and repo:
                gh = GH(gh_token)
                ref = base_branch or gh.get_default_branch(owner, repo)
                discovered_apps = list_apps(gh, owner, repo, base_path, ref)
        except Exception as e:
            st.info(f"App discovery skipped: {e}")

        app_label = st.selectbox("App (folder name)", options=(discovered_apps or [os.environ.get("APP_LABEL", "app1")]))

        try:
            if gh_token and owner and repo and app_label:
                gh = GH(gh_token)
                ref = base_branch or gh.get_default_branch(owner, repo)
                discovered_values = list_value_files(gh, owner, repo, app_label, base_path, ref)
        except Exception as e:
            st.info(f"Value file discovery skipped: {e}")

        yaml_filename = st.selectbox("Values file", options=(discovered_values or ["values-dev-us.yaml"]))
        yaml_path = f"{base_path}/{app_label}/{yaml_filename}"

        st.caption("App & values are discovered live from the repo. You can override the path below if needed.")
        yaml_path = st.text_input("YAML path (override)", value=yaml_path)

        st.divider()
        st.subheader("Production Workflows (optional)")
        workflow_file = st.text_input("Workflow filename", value=os.environ.get("WORKFLOW_FILE", "ci-tests.yml"))
        workflow_ref = st.text_input("Workflow ref (branch/tag)", value=os.environ.get("WORKFLOW_REF", ""))

        return {
            "gh_token": gh_token,
            "owner": owner,
            "repo": repo,
            "base_branch": base_branch,
            "app_label": app_label,
            "yaml_path": yaml_path,
            "workflow_file": workflow_file,
            "workflow_ref": workflow_ref,
        }

def ensure_gh(cfg: Dict) -> Tuple[GH, str]:
    if not cfg["gh_token"]:
        st.error("Please provide a GitHub token (or set GITHUB_TOKEN env var).")
        st.stop()
    gh = GH(cfg["gh_token"])
    base_branch = cfg["base_branch"] or gh.get_default_branch(cfg["owner"], cfg["repo"])
    return gh, base_branch

def section_nonprod(cfg: Dict):
    st.subheader("Non-Production")
    env_label = st.text_input("Env label", value=os.environ.get("ENV_LABEL_NONPROD", "dev-us"))
    action = st.radio("Update target", ["primary (active)", "standby"], index=1)
    new_version = st.text_input("Version to set", value="1.2.3")

    # Optional flip controls for non-prod
    st.markdown("**Optional:** Flip active slot in non-prod")
    off_switch_np = st.checkbox("Turn off standby switch after non-prod flip", value=False)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Generate PR for version update", type="primary"):
            gh, base_branch = ensure_gh(cfg)
            # Detect active to choose target slot intelligently
            doc, _, _ = load_yaml_from_repo(gh, cfg["owner"], cfg["repo"], cfg["yaml_path"], base_branch)
            active = detect_active_slot(doc)
            target = active if action.startswith("primary") else standby_slot(active)

            res = propose_version_update(
                gh,
                cfg["owner"],
                cfg["repo"],
                base_branch,
                cfg["yaml_path"],
                cfg["app_label"],
                env_label,
                target,
                new_version,
            )
            pr = res["pr"]
            st.success("PR created!")
            st.write(f"**PR:** [{pr['title']}]({pr['html_url']})  ")

    with c2:
        if st.button("Auto Flip active slot (Non-Prod)"):
            gh, base_branch = ensure_gh(cfg)
            res = propose_auto_flip(
                gh,
                cfg["owner"],
                cfg["repo"],
                base_branch,
                cfg["yaml_path"],
                cfg["app_label"],
                env_label,
                turn_off_switch=off_switch_np,
            )
            pr = res["pr"]
            st.success(f"Auto-flip PR created! New active: {res['new_active']}")
            st.write(f"**PR:** [{pr['title']}]({pr['html_url']})  ")

def section_prod(cfg: Dict):
    st.subheader("Production")
    env_label = st.text_input("Env label (prod variant)", value=os.environ.get("ENV_LABEL_PROD", "prod-us"))
    new_version = st.text_input("Standby version to set", value="2.0.0")

    c1, c2 = st.columns(2)
    with c1:
        trigger_tests = st.checkbox("Trigger GitHub Actions tests after PR", value=True)
    with c2:
        auto_flip_ready = st.checkbox("Enable Auto Flip step", value=True)

    turn_off_req = st.checkbox("Turn off standby switch after flip", value=False)

    inputs_raw = st.text_area(
        "Workflow inputs (JSON)",
        value=json.dumps({"app": os.environ.get("APP_LABEL", "app1"), "env": "prod", "version": "2.0.0"}, indent=2),
        height=140,
    )

    if st.button("Create PR to update STANDBY version", type="primary"):
        gh, base_branch = ensure_gh(cfg)
        doc, _, _ = load_yaml_from_repo(gh, cfg["owner"], cfg["repo"], cfg["yaml_path"], base_branch)
        active = detect_active_slot(doc)
        target = standby_slot(active)

        res = propose_version_update(
            gh,
            cfg["owner"],
            cfg["repo"],
            base_branch,
            cfg["yaml_path"],
            cfg["app_label"],
            env_label,
            target,
            new_version,
        )
        pr = res["pr"]
        st.success("Standby update PR created!")
        st.write(f"**PR:** [{pr['title']}]({pr['html_url']})  ")

        if trigger_tests and cfg["workflow_file"]:
            try:
                inputs = json.loads(inputs_raw) if inputs_raw.strip() else {}
            except Exception as e:
                st.error(f"Invalid workflow inputs JSON: {e}")
                st.stop()
            ref = cfg["workflow_ref"] or cfg["base_branch"] or base_branch
            _ = gh.dispatch_workflow(cfg["owner"], cfg["repo"], cfg["workflow_file"], ref, inputs)
            st.info("Workflow dispatched. Check Actions for run status.")

    st.divider()
    st.markdown("### Auto Flip (after tests verified)")
    if auto_flip_ready and st.button("Create PR to AUTO FLIP active slot"):
        gh, base_branch = ensure_gh(cfg)
        res = propose_auto_flip(
            gh,
            cfg["owner"],
            cfg["repo"],
            base_branch,
            cfg["yaml_path"],
            cfg["app_label"],
            env_label,
            turn_off_switch=turn_off_req,
        )
        pr = res["pr"]
        st.success(f"Auto-flip PR created! New active: {res['new_active']}")
        st.write(f"**PR:** [{pr['title']}]({pr['html_url']})  ")

def main():
    ui_header()
    cfg = ui_sidebar()
    st.markdown(
        "> **Tip:** Point `YAML path` to the exact file (e.g., `apps/app2/values-qa.yaml`).\n"
        "> The app will read it, detect the active slot, and generate PRs accordingly."
    )
    tab1, tab2 = st.tabs(["Non-Prod", "Prod"])
    with tab1:
        section_nonprod(cfg)
    with tab2:
        section_prod(cfg)

if __name__ == "__main__":
    main()
