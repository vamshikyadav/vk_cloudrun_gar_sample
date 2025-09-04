terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.30.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- Enable required APIs ---
locals {
  required_apis = [
    "run.googleapis.com",
    "dataflow.googleapis.com",
    "logging.googleapis.com",
    "aiplatform.googleapis.com"
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# --- Service account for Cloud Run runtime ---
resource "google_service_account" "run_sa" {
  account_id   = var.service_account_id != "" ? var.service_account_id : "${var.service_name}-sa"
  display_name = "Cloud Run SA for ${var.service_name}"
}

# --- IAM roles for runtime SA ---
locals {
  sa_roles = concat([
    "roles/dataflow.viewer",
    "roles/logging.viewer",
    "roles/aiplatform.user",
    "roles/serviceusage.serviceUsageConsumer"
  ], var.additional_sa_roles)
}

resource "google_project_iam_member" "sa_role_bindings" {
  for_each = toset(local.sa_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.run_sa.email}"
}

# --- Cloud Run (v2) service ---
resource "google_cloud_run_v2_service" "svc" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.run_sa.email

    containers {
      image = var.image

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "DATAFLOW_REGION"
        value = var.dataflow_region
      }
      env {
        name  = "VERTEX_REGION"
        value = var.vertex_region
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }
    }

    # Concurrency / autoscaling
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Optional VPC connector
    dynamic "vpc_access" {
      for_each = var.vpc_connector == "" ? [] : [1]
      content {
        connector = var.vpc_connector
        egress    = var.vpc_egress
      }
    }
  }

  traffic {
    type            = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent         = 100
    revision        = null
    tag             = null
  }

  depends_on = [google_project_service.apis]
}

# --- Public access (optional) ---
resource "google_cloud_run_v2_service_iam_member" "invoker_all" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.svc.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
