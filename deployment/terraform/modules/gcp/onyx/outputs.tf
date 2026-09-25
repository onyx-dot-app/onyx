output "cluster_name" {
  description = "Name of the GKE cluster"
  value       = module.gke.cluster_name
}

output "location" {
  description = "Region of the cluster. gcloud container clusters get-credentials takes this as --location."
  value       = module.gke.location
}

output "cluster_endpoint" {
  description = "API server URL for the kubernetes and helm providers"
  value       = module.gke.endpoint
  sensitive   = true
}

# A CA certificate is public by design, so this is not marked sensitive.
output "cluster_ca_certificate" {
  description = "Cluster CA certificate, base64 encoded"
  value       = module.gke.cluster_ca_certificate
}

output "workload_identity_principal" {
  description = "IAM member for the workload service account, for granting it roles on resources outside this module"
  value       = module.gke.workload_identity_principal
}

output "workload_namespace" {
  description = "Namespace of the workload service account. Install the Helm release into it."
  value       = module.gke.workload_namespace
}

output "workload_service_account_name" {
  description = "Kubernetes service account that holds the bucket grant. Set it as the chart's serviceAccount.name."
  value       = module.gke.workload_service_account_name
}

output "node_service_account_email" {
  description = "Service account the nodes run as. Grant it roles/artifactregistry.reader on a registry in another project to pull from it."
  value       = module.gke.node_service_account_email
}

# With a supplied network these are read off the ids given, so they name what
# the cluster joined either way.
output "network_name" {
  description = "Name of the VPC network the cluster joins"
  value       = var.create_network ? module.vpc[0].network_name : element(reverse(split("/", var.network_id)), 0)
}

output "subnet_name" {
  description = "Name of the subnet the nodes join"
  value       = var.create_network ? module.vpc[0].subnet_name : element(reverse(split("/", var.subnet_id)), 0)
}

# --- Values the Helm chart needs ---------------------------------------------

output "gcs_bucket_name" {
  description = "Set as GCS_FILE_STORE_BUCKET_NAME"
  value       = module.gcs.bucket_name
}

output "gcs_project_id" {
  description = "Set as GCS_PROJECT_ID"
  value       = var.project_id
}

output "postgres_host" {
  description = "Private IP of the database. Set as POSTGRES_HOST."
  value       = module.postgres.host
}

output "postgres_port" {
  description = "Database port. Set as POSTGRES_PORT."
  value       = module.postgres.port
}

output "postgres_db_name" {
  description = "Database name. Set as POSTGRES_DB; Onyx falls back to \"postgres\" without it."
  value       = module.postgres.db_name
}

output "postgres_username" {
  description = "Login Onyx connects as. Set as POSTGRES_USER."
  value       = module.postgres.username
  sensitive   = true
}

output "redis_host" {
  description = "Private IP of the cache, null when enable_redis is false. Set as REDIS_HOST."
  value       = one(module.redis[*].host)
}

output "redis_port" {
  description = "Cache port: 6379, or 6378 with transit encryption. Set as REDIS_PORT."
  value       = one(module.redis[*].port)
}

# Memorystore generates this rather than accepting one, so it comes out of the
# module rather than going in.
output "redis_auth_string" {
  description = "Generated AUTH string. Set as REDIS_PASSWORD through a secret."
  value       = one(module.redis[*].auth_string)
  sensitive   = true
}

output "redis_url_scheme" {
  description = "\"rediss\" with transit encryption, \"redis\" without. With rediss, set REDIS_SSL=true."
  value       = one(module.redis[*].redis_url_scheme)
}

output "cloud_armor_policy_name" {
  description = "Cloud Armor policy to name in a BackendConfig or GCPBackendPolicy, null when disabled"
  value       = try(module.cloud_armor[0].policy_name, null)
}
