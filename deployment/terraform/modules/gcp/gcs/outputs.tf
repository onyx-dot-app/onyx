output "bucket_name" {
  description = "Name of the bucket. Set this as GCS_FILE_STORE_BUCKET_NAME."
  value       = google_storage_bucket.this.name
}

output "bucket_url" {
  description = "gs:// URL of the bucket"
  value       = google_storage_bucket.this.url
}

output "bucket_self_link" {
  description = "API self link of the bucket"
  value       = google_storage_bucket.this.self_link
}

output "kms_key_name" {
  description = "Cloud KMS key the bucket encrypts with. Null when the bucket uses Google-managed keys."
  value       = local.kms_key_name
}
