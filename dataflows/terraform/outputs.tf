output "service_url" {
  description = "Cloud Run HTTPS URL."
  value       = google_cloud_run_v2_service.svc.uri
}

output "service_account_email" {
  description = "Runtime service account email."
  value       = google_service_account.run_sa.email
}

output "service_name" {
  value       = google_cloud_run_v2_service.svc.name
  description = "Deployed Cloud Run service name."
}
