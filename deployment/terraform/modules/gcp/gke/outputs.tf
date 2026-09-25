output "cluster_name" {
  description = "Name of the cluster"
  value       = google_container_cluster.this.name
}

output "cluster_id" {
  description = "ID of the cluster, in projects/<project>/locations/<location>/clusters/<name> form"
  value       = google_container_cluster.this.id
}

output "location" {
  description = "Region of a regional cluster, or zone of a zonal one. gcloud and kubectl credentials take this as --location."
  value       = google_container_cluster.this.location
}

# With private_endpoint_enabled GKE reports the private address here, which
# resolves only from inside the network.
output "endpoint" {
  description = "API server URL, for configuring the kubernetes and helm providers"
  value       = "https://${google_container_cluster.this.endpoint}"
}

# A CA certificate is public by design. Marking it sensitive would only hide
# it from plans that need to show which cluster a provider points at.
output "cluster_ca_certificate" {
  description = "Cluster CA certificate, base64 encoded, for configuring the kubernetes and helm providers"
  value       = try(google_container_cluster.this.master_auth[0].cluster_ca_certificate, null)
}

output "workload_identity_pool" {
  description = "Workload identity pool of the cluster, <project>.svc.id.goog"
  value       = local.workload_pool
}

output "node_service_account_email" {
  description = "Service account the nodes run as. Grant it roles/artifactregistry.reader on a registry in another project to pull from it."
  value       = google_service_account.nodes.email
}

output "node_pool_names" {
  description = "Generated names of every node pool, keyed by the pool key"
  value       = { for k, p in google_container_node_pool.this : k => p.name }
}

output "workload_namespace" {
  description = "Namespace of the workload service account"
  value       = var.create_workload_namespace ? kubernetes_namespace.workload[0].metadata[0].name : var.workload_namespace
}

output "workload_service_account_name" {
  description = "Kubernetes service account that workload identity grants reach"
  value       = var.create_workload_service_account ? kubernetes_service_account.workload[0].metadata[0].name : var.workload_service_account_name
}

# IAM names a Kubernetes service account by project number, not project ID.
# Built from the inputs rather than the created objects, so a caller can key a
# for_each on it: the value is known at plan time and does not need the
# account to exist yet.
output "workload_identity_principal" {
  description = "IAM member for the workload service account. Use it as the member of a role binding, for example on a bucket, to grant that access to pods running as the account."
  value       = "principal://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${local.workload_pool}/subject/ns/${var.workload_namespace}/sa/${var.workload_service_account_name}"
}
