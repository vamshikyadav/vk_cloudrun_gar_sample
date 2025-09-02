#!/usr/bin/env bash
set -euo pipefail

echo "== Cloud Run Job | Dataflow launcher =="

# Required vars check
req=(PROJECT_ID REGION ENV JOB_NAME_BASE GCS_STAGING_BUCKET GCS_TEMP_BUCKET NEXUS_URL NEXUS_USER NEXUS_PASSWORD)
for v in "${req[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    echo "Missing required env var: $v" >&2
    exit 2
  fi
done

# Get an access token (ADC provided automatically on Cloud Run)
gcloud -q auth list >/dev/null || true
echo "Project: ${PROJECT_ID} | Region: ${REGION} | Env: ${ENV}"

# 1) Download JAR from Nexus
JAR_PATH="/app/pipeline.jar"
echo "Downloading JAR from Nexus..."
curl -fSL -u "${NEXUS_USER}:${NEXUS_PASSWORD}" "${NEXUS_URL}" -o "${JAR_PATH}"
echo "JAR size: $(stat -c%s "${JAR_PATH}") bytes"

# 2) Build job name (prefix with env)
TS=$(date +%Y%m%d-%H%M%S)
JOB_NAME="${ENV}-${JOB_NAME_BASE}-${TS}"
echo "Job name: ${JOB_NAME}"

# 3) Run the pipeline to submit to Dataflow
#   NOTE: your JAR must accept standard DataflowRunner options
#   e.g. --runner=DataflowRunner --project --region --stagingLocation --tempLocation --jobName
JAVA_CMD=(java ${JAVA_HEAP} -jar "${JAR_PATH}"
  --runner=DataflowRunner
  --project="${PROJECT_ID}"
  --region="${REGION}"
  --stagingLocation="gs://${GCS_STAGING_BUCKET}/staging"
  --tempLocation="gs://${GCS_TEMP_BUCKET}/tmp"
  --jobName="${JOB_NAME}"
)

# Append user-provided args, split safely
if [[ -n "${PIPELINE_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  EXTRA_ARGS=(${PIPELINE_ARGS})
  JAVA_CMD+=("${EXTRA_ARGS[@]}")
fi

echo "Submitting Dataflow job..."
set +e
"${JAVA_CMD[@]}" | tee /tmp/submit.log
SUBMIT_RC=$?
set -e

if [[ ${SUBMIT_RC} -ne 0 ]]; then
  echo "Pipeline submission command returned ${SUBMIT_RC}."
  # We still try to find a jobId in case submission actually reached the service
fi

# 4) Discover jobId (find by name in the last 15 minutes)
echo "Resolving jobId..."
JOB_ID=$(gcloud dataflow jobs list \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --filter="NAME:${JOB_NAME} AND (STATE=Running OR STATE=Pending OR STATE=Queued OR STATE=Draining OR STATE=Cancelling OR STATE=Stopped OR STATE=Failed OR STATE=Done)" \
  --format="value(id)" | head -n1)

if [[ -z "${JOB_ID}" ]]; then
  echo "Could not find a matching Dataflow job for ${JOB_NAME}. Check logs."
  exit ${SUBMIT_RC}
fi

echo "Found jobId: ${JOB_ID}"

publish_event () {
  local phase="$1"
  local state="$2"
  local msg="${3:-}"
  if [[ -n "${PUBSUB_TOPIC:-}" ]]; then
    gcloud pubsub topics publish "${PUBSUB_TOPIC}" \
      --project="${PROJECT_ID}" \
      --message "{\"env\":\"${ENV}\",\"jobName\":\"${JOB_NAME}\",\"jobId\":\"${JOB_ID}\",\"phase\":\"${phase}\",\"state\":\"${state}\",\"ts\":\"$(date -Is)\"${msg:+,${msg}}}" \
      --attributes="env=${ENV},state=${state},jobName=${JOB_NAME}" >/dev/null || true
  fi
}

publish_event "submitted" "UNKNOWN"

# 5) Poll until terminal state
TERMINAL_STATES=("Done" "Failed" "Cancelled" "Updated")
SLEEP=30
echo "Polling job state every ${SLEEP}s..."
while true; do
  STATE=$(gcloud dataflow jobs describe "${JOB_ID}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format="value(currentState)")

  STATE=${STATE:-UNKNOWN}
  echo "State: ${STATE}"
  publish_event "poll" "${STATE}"

  for t in "${TERMINAL_STATES[@]}"; do
    if [[ "${STATE}" == "${t}" ]]; then
      echo "Reached terminal state: ${STATE}"
      publish_event "finished" "${STATE}"
      if [[ "${STATE}" == "Done" ]]; then
        exit 0
      else
        exit 1
      fi
    fi
  done

  sleep "${SLEEP}"
done
