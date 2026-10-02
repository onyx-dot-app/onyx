output "policy_name" {
  description = "Name of the policy. Put it in a BackendConfig securityPolicy.name or a GCPBackendPolicy securityPolicy."
  value       = google_compute_security_policy.this.name
}

output "policy_id" {
  description = "ID of the policy"
  value       = google_compute_security_policy.this.id
}

output "policy_self_link" {
  description = "Self link of the policy, for a backend service's security_policy"
  value       = google_compute_security_policy.this.self_link
}

# Unlike the AWS module there is no log group here. Cloud Armor writes its
# decisions to the request logs of the backend service the policy is attached
# to, so logging is turned on there.
output "preview" {
  description = "Whether the WAF and rate limit rules only log by default"
  value       = var.preview
}
