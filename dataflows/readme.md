### build image
gcloud builds submit --tag gcr.io/PROJECT_ID/dataflow-trigger

### Deploy
gcloud run deploy dataflow-trigger \
  --image gcr.io/PROJECT_ID/dataflow-trigger \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated

### Sample Request

curl -X POST \
  "https://YOUR_CLOUD_RUN_URL/trigger?country=us&env=qa"

### Response

{
  "status": "success",
  "stdout": "... Dataflow job started ..."
}
