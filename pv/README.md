# Blue/Green PR Orchestrator (Streamlit)

Features:
- Detects active blue/green slot (case-insensitive)
- Updates primary/standby versions (case-insensitive appversion keys)
- Auto-flip PR that sets both sections' `activeslot` and enforces weights (primary 100/0, standby 0/100)
- Optional: turn OFF standby switch (`blueswitch`/`greenswitch` case-insensitive)
- Lists app folders and `values*.y(a)ml` files from your repo via dropdowns
- Triggers GitHub Actions with custom inputs
- Cloud Run ready; reads defaults from env vars

## Env Vars
- `GITHUB_TOKEN` (required)
- `GH_OWNER`, `GH_REPO`, `GH_BRANCH`
- `APPS_ROOT` (default `apps`)
- `APP_LABEL`, `YAML_PATH`
- `WORKFLOW_FILE`, `WORKFLOW_REF`
- `ENV_LABEL_NONPROD` (default `dev-us`), `ENV_LABEL_PROD` (default `prod-us`)

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Cloud Run
```bash
gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/bluegreen-orchestrator
gcloud run deploy bluegreen-orchestrator   --image gcr.io/$(gcloud config get-value project)/bluegreen-orchestrator   --region us-central1 --allow-unauthenticated   --set-env-vars PORT=8080,GITHUB_TOKEN=REDACTED,GH_OWNER=your-org,GH_REPO=your-repo,GH_BRANCH=main,APPS_ROOT=apps
```
