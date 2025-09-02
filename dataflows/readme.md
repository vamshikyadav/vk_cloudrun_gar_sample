# Cloud Run Jobs
They’re built for finite work. You avoid HTTP timeouts and can run until the Dataflow submission/poll completes (task timeout up to 24h). Use a Service only for a REST trigger front-door.

## Cloud Run Job (main worker):
On start: pulls pipeline JAR from Nexus.
Submits Dataflow job with env-specific name/args.
Polls Dataflow state until terminal (Done/Failed/Cancelled).
Publishes progress to a Pub/Sub topic (dataflow-events) and logs to Cloud Logging

## Cloud Run Service API:

Endpoints to trigger the Job (/run?env=dev&job=etl-x) and to read recent status from Pub/Sub/BigQuery.

Composer-like trigger & visibility feel.

## IAM:

Cloud Run job’s service account: 
roles/dataflow.developer, 
roles/storage.objectAdmin (staging/temp buckets), 
roles/pubsub.publisher, 
roles/secretmanager.secretAccessor (for Nexus creds),  
roles/logging.logWriter.

# Required access 
## Vars
PROJECT_ID="your-project"
REGION="us-central1"
ENV="dev"  # dev|qa|prod
JOB_NAME_BASE="orders-etl"
STAGING_BUCKET="your-staging-bkt"
TEMP_BUCKET="your-temp-bkt"
PUBSUB_TOPIC="df-events"

gcloud config set project $PROJECT_ID

## Buckets (if not exist)
gsutil mb -l $REGION gs://$STAGING_BUCKET/
gsutil mb -l $REGION gs://$TEMP_BUCKET/

## Pub/Sub topic for status
gcloud pubsub topics create $PUBSUB_TOPIC

## Build & push image
gcloud builds submit --tag "gcr.io/$PROJECT_ID/dataflow-launcher:latest"

## Create a service account
gcloud iam service-accounts create df-launcher --display-name="Dataflow Launcher"

## IAM
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:df-launcher@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/dataflow.developer"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:df-launcher@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:df-launcher@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:df-launcher@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:df-launcher@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

## Store Nexus creds in Secret Manager (example)
echo -n 'https://nexus.example.com/repository/.../pipeline.jar' | gcloud secrets create NEXUS_URL --data-file=-
echo -n 'nexus-user' | gcloud secrets create NEXUS_USER --data-file=-
echo -n 'nexus-pass' | gcloud secrets create NEXUS_PASSWORD --data-file=-

# Create the Cloud Run Job
gcloud run jobs create df-launcher-job \
  --image "gcr.io/$PROJECT_ID/dataflow-launcher:latest" \
  --region $REGION \
  --service-account "df-launcher@$PROJECT_ID.iam.gserviceaccount.com" \
  --set-env-vars "PROJECT_ID=$PROJECT_ID,REGION=$REGION,ENV=$ENV,JOB_NAME_BASE=$JOB_NAME_BASE,GCS_STAGING_BUCKET=$STAGING_BUCKET,GCS_TEMP_BUCKET=$TEMP_BUCKET,PUBSUB_TOPIC=$PUBSUB_TOPIC" \
  --set-secrets "NEXUS_URL=NEXUS_URL:latest,NEXUS_USER=NEXUS_USER:latest,NEXUS_PASSWORD=NEXUS_PASSWORD:latest" \
  --max-retries=0 \
  --cpu=1 --memory=1Gi \
  --task-timeout=3600s   # up to 24h if you wish

# Run it with different envs
## Dev
gcloud run jobs execute df-launcher-job --region $REGION --set-env-vars "ENV=dev,JOB_NAME_BASE=orders-etl"

## Prod with extra pipeline args
gcloud run jobs execute df-launcher-job --region $REGION \
  --set-env-vars "ENV=prod,JOB_NAME_BASE=orders-etl" \
  --set-env-vars 'PIPELINE_ARGS=--input=gs://prod-bkt/input --output=gs://prod-bkt/out --workerMachineType=n2-standard-4 --numWorkers=4'
