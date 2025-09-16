PROJECT_ID=YOUR_PROJECT
REGION=us-central1
SERVICE=streamlit-dataflow-health

gcloud auth configure-docker $REGION-docker.pkg.dev
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/apps/$SERVICE:latest .
docker push $REGION-docker.pkg.dev/$PROJECT_ID/apps/$SERVICE:latest

gcloud run deploy $SERVICE \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/apps/$SERVICE:latest \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars PROJECT_ID=$PROJECT_ID,DATAFLOW_REGION=us-central1,VERTEX_REGION=us-central1

VPC access:
gcloud run deploy $SERVICE \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/apps/$SERVICE:latest \
  --region us-central1 \
  --vpc-connector YOUR_CONNECTOR_NAME \
  --vpc-egress all \
  --set-env-vars PROJECT_ID=$PROJECT_ID,DATAFLOW_REGION=us-central1,VERTEX_REGION=us-central1

## Local Testing:
### Uses your ADC: gcloud auth application-default login
export PROJECT_ID=YOUR_PROJECT
export DATAFLOW_REGION=us-central1
export VERTEX_REGION=us-central1
streamlit run app.py --server.port=8080 --server.headless=true


## Call service with a signed token
ID_TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer ${ID_TOKEN}" \
  https://<cloud-run-url>/

