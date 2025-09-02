# Minimal Debian with Java + gcloud
FROM debian:bookworm-slim

# Install deps: curl, jq, Java 17, and Google Cloud SDK
RUN apt-get update && apt-get install -y curl gnupg ca-certificates jq openjdk-17-jre \
 && curl -sSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list \
 && apt-get update && apt-get install -y google-cloud-cli \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Environment (override at deploy time)
ENV JAVA_HEAP="-Xms512m -Xmx1024m"
ENV REGION="us-central1"
ENV ENV="dev"                        # dev | qa | prod
ENV JOB_NAME_BASE="my-pipeline"
ENV PROJECT_ID=""
ENV GCS_STAGING_BUCKET=""
ENV GCS_TEMP_BUCKET=""

# Nexus info (store real values in Secret Manager and mount as env)
ENV NEXUS_URL=""
ENV NEXUS_USER=""
ENV NEXUS_PASSWORD=""

# Extra pipeline args (space-separated, e.g. '--input=gs://... --output=gs://...')
ENV PIPELINE_ARGS=""

# Where to publish progress updates
ENV PUBSUB_TOPIC="df-events"

ENTRYPOINT ["/app/entrypoint.sh"]
