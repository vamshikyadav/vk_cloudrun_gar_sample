variable "project_id" {
  type        = string
  description = "GCP project ID to deploy into."
}

variable "region" {
  type        = string
  description = "Region for Cloud Run (e.g., us-central1)."
  default     = "us-central1"
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name."
  default     = "streamlit-dataflow-health"
}

variable "image" {
  type        = string
  description = "Container image (Artifact Registry URL), e.g. us-central1-docker.pkg.dev/PROJECT/apps/streamlit:latest"
}

variable "dataflow_region" {
  type        = string
  description = "Dataflow region to query."
  default     = "us-central1"
}

variable "vertex_region" {
  type        = string
  description = "Vertex AI region."
  default     = "us-central1"
}

variable "service_account_id" {
  type        = string
  description = "Optional custom SA ID (without domain). If empty, derived from service_name."
  default     = ""
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Grant public (allUsers) invoker access."
  default     = true
}

variable "cpu" {
  type        = string
  description = "Container CPU limit (e.g., 1, 2)."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Container memory limit (e.g., 512Mi, 1Gi)."
  default     = "1Gi"
}

variable "min_instances" {
  type        = number
  description = "Minimum instances for Cloud Run autoscaling."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Maximum instances for Cloud Run autoscaling."
  default     = 10
}

variable "vpc_connector" {
  type        = string
  description = "Optional Serverless VPC Connector name (projects/PROJECT/locations/REGION/connectors/NAME or just NAME if same project/region)."
  default     = ""
}

variable "vpc_egress" {
  type        = string
  description = "Egress setting when VPC connector is set. One of: ALL_TRAFFIC or PRIVATE_RANGES_ONLY."
  default     = "ALL_TRAFFIC"
}

variable "additional_sa_roles" {
  type        = list(string)
  description = "Extra project-level roles to bind to the runtime SA."
  default     = []
}
