# Cloud Run Java Sample — README

A minimal Spring Boot HTTP API packaged in a container and deployed to Cloud Run. This guide covers local build, containerization, pushing to Artifact Registry, multiple deployment patterns (public, private/"internal"), environment variables, networking (Direct VPC egress **or** Serverless VPC Connector), logging, and troubleshooting.

---

## 0) Prerequisites

- **gcloud CLI** installed and initialized (`gcloud init`)
- **Docker** installed and logged in
- **Java 17** and **Maven** if you want to build locally
- A Google Cloud **project** with billing enabled

```bash
# Authenticate
gcloud auth login

# Select project & region
PROJECT_ID="your-project-id"
REGION="us-east1"
gcloud config set project $PROJECT_ID
```

---

## 1) Source Layout

```
cloudrun-demo/
├─ pom.xml
├─ Dockerfile
└─ src/main/...
```

The app binds to the `PORT` env var (defaults to 8080 locally). Endpoints:

- `GET /` returns a hello JSON
- `GET /health` returns `{status: ok}`
- `GET /echo?msg=hi` echos back your query

---

## 2) Build Application

```bash
# From the project root
mvn -q -DskipTests package
```

This produces `target/cloudrun-demo-0.0.1.jar`.

---

## 3) Create Artifact Registry & Push Image

```bash
REPO="demo"       # choose a repo name
IMAGE="cloudrun-demo"
TAG="v1"

# Create a Docker repo once (no-op if it exists)
gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$REGION || true

# Build
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$TAG .

# Allow docker to push to Artifact Registry (once)
gcloud auth configure-docker $REGION-docker.pkg.dev

# Push
docker push $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$TAG
```

---

## 4) (Option A) Public Service — Fastest Path

```bash
SERVICE="cloudrun-demo"

gcloud run deploy $SERVICE \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$TAG \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars=SOME_KEY=some_value

# Get URL
URL=$(gcloud run services describe $SERVICE --region $REGION --format='value(status.url)')

# Smoke tests
curl -s "$URL/" | jq .
curl -s "$URL/health" | jq .
curl -s "$URL/echo?msg=hi" | jq .
```

---

## 5) (Option B) Private Ingress + Direct VPC Egress (network/subnet)

**Use this if you want the service reachable only internally and all/most egress to go through your VPC.**

> Pre-reqs: A subnet in the **same region** as Cloud Run. Ensure NAT/egress is configured if your app needs public internet during startup.

```bash
SERVICE="cloudrun-internal"
NETWORK="YOUR_SHARED_VPC_NAME"      # e.g., my-svpc
SUBNET="YOUR_SHARED_SUBNET_NAME"    # e.g., my-svpc-subnet-us-east1

# Deploy with internal ingress and direct VPC egress
gcloud run deploy $SERVICE \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$TAG \
  --region=$REGION \
  --platform=managed \
  --no-allow-unauthenticated \
  --ingress=internal \
  --network=$NETWORK \
  --subnet=$SUBNET \
  --vpc-egress=private-ranges-only \
  --set-env-vars=SOME_KEY=some_value

# (Optional) Route *all* egress via VPC (requires NAT for internet access)
# --vpc-egress=all-traffic
```

> **Accessing an internal service:** Attach an **internal HTTPS Load Balancer** (serverless NEG) or **Private Service Connect**. Without that, the service is not directly reachable.

---

## 6) (Option C) Private Ingress + Serverless VPC Connector

If you prefer the traditional connector approach:

```bash
CONNECTOR="cr-us-east1"
VPC_NETWORK="YOUR_VPC"
VPC_SUBNET="YOUR_SUBNET"

# Create the connector once
gcloud compute networks vpc-access connectors create $CONNECTOR \
  --region=$REGION \
  --network=$VPC_NETWORK \
  --subnet=$VPC_SUBNET

# Deploy using the connector (egress for RFC1918 only)
SERVICE="cloudrun-connector"
gcloud run deploy $SERVICE \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$TAG \
  --region=$REGION \
  --platform=managed \
  --no-allow-unauthenticated \
  --ingress=internal-and-cloud-load-balancing \
  --vpc-connector=$CONNECTOR \
  --vpc-egress=private-ranges-only \
  --set-env-vars=SOME_KEY=some_value
```

---

## 7) Environment Variables & Secrets

### Set env vars at deploy

```bash
--set-env-vars=KEY1=VALUE1,KEY2=VALUE2
```

### From file (YAML)

```bash
gcloud run deploy $SERVICE \
  ... \
  --set-env-vars-file=env.yaml
# env.yaml
# DB_HOST: db.example.com
# DB_USER: admin
# DB_PASS: "secret"
```

### Secret Manager (recommended for secrets)

```bash
# Create secret versions
echo -n "s3cr3t" | gcloud secrets create db-password --data-file=-

# Grant runtime service account access
RUNTIME_SA="my-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud secrets add-iam-policy-binding db-password \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor"

# Mount as env var at deploy
gcloud run deploy $SERVICE \
  ... \
  --update-secrets=DB_PASSWORD=db-password:latest
```

---

## 8) Useful Runtime Flags

```bash
# Give the app more time to start (default ~4m)
--revision-timeout=10m

# Keep a warm instance ready (faster cold-start)
--min-instances=1

# Set service account explicitly (for accessing other GCP services)
--service-account=my-runtime@${PROJECT_ID}.iam.gserviceaccount.com
```

---

## 9) Logs & Troubleshooting

### Quick service logs

```bash
gcloud run services logs read $SERVICE --region $REGION --limit 100
# Live tail
gcloud run services logs tail $SERVICE --region $REGION
```

### Get latest revision and describe events

```bash
REVISION_NAME="$(gcloud run services describe $SERVICE --region=$REGION \
  --format='value(status.latestCreatedRevisionName)')"

echo $REVISION_NAME

gcloud run revisions describe "$REVISION_NAME" --region=$REGION
```

### Common issues

- **Deadline exceeded during deploy**: container never became Ready. Check:
  - App binds to `$PORT`
  - NAT/egress present if using `--vpc-egress=all-traffic`
  - Subnet/connector region matches Cloud Run region
  - Runtime service account has required perms (Secret Manager, Artifact Registry, etc.)

---

## 10) Update, Rollback, Cleanup

```bash
# Update to a new image tag
NEW_TAG=v2
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$NEW_TAG .
docker push $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$NEW_TAG

gcloud run deploy $SERVICE \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$NEW_TAG \
  --region=$REGION

# List revisions
gcloud run revisions list --region=$REGION --service=$SERVICE

# Roll back to a previous ready revision
OLD_REV="rev-00002"
gcloud run services update-traffic $SERVICE --region=$REGION \
  --to-revisions=${OLD_REV}=100

# Cleanup (service + repository)
gcloud run services delete $SERVICE --region=$REGION
# Optional: delete the image or entire repo
# gcloud artifacts docker images delete $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:$TAG
# gcloud artifacts repositories delete $REPO --location=$REGION
```

---

## 11) Minimal Curl Test (internal via LB/PSC)

If you front an internal service with an internal HTTPS LB or PSC, curl from a VM in the same VPC:

```bash
curl -s https://INTERNAL_DNS_OR_IP/health
```

---

## 12) Notes on Direct VPC vs Connector

- **Direct VPC egress**: simpler; specify `--network` and `--subnet`. Ensure subnet capacity and NAT.
- **Serverless VPC Connector**: works across products; fine-grained control; one more resource to manage.

Pick whichever aligns with your org standards and networking architecture.

---

**That’s it!** You now have a repeatable set of commands to build, push, deploy, test, and operate a Java API on Cloud Run.

