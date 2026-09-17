output "resource_group_name" {
  description = "Resource group holding the deployment"
  value       = local.resource_group_name
}

output "cluster_name" {
  description = "Name of the AKS cluster"
  value       = module.aks.cluster_name
}

output "cluster_fqdn" {
  description = "API server hostname"
  value       = module.aks.cluster_fqdn
}

output "oidc_issuer_url" {
  description = "OIDC issuer URL of the cluster, the trust anchor for federated credentials"
  value       = module.aks.oidc_issuer_url
}

output "workload_identity_client_id" {
  description = "Client ID of the workload identity. Set this as the azure.workload.identity/client-id annotation on any service account the module did not create."
  value       = module.aks.workload_identity_client_id
}

# The client id annotates a service account; a role assignment needs the
# principal id instead. Granting this identity access to anything the
# composition does not itself create - a key vault, another storage account -
# is impossible without it.
output "workload_identity_principal_id" {
  description = "Principal ID of the workload identity, for granting it roles on resources outside this module"
  value       = module.aks.workload_identity_principal_id
}

output "cluster_identity_principal_id" {
  description = "Principal ID of the cluster identity, for granting it roles on network resources this module does not own -- an ingress public IP, most often"
  value       = module.aks.cluster_identity_principal_id
}

output "node_resource_group" {
  description = "Resource group AKS creates for the cluster's own infrastructure"
  value       = module.aks.node_resource_group
}

# --- Values the Helm chart needs ---------------------------------------------

output "storage_account_name" {
  description = "Set as AZURE_STORAGE_ACCOUNT_NAME"
  value       = module.storage.storage_account_name
}

output "storage_account_url" {
  description = "Set as AZURE_STORAGE_ACCOUNT_URL"
  value       = module.storage.primary_blob_endpoint
}

output "storage_container_name" {
  description = "Set as AZURE_FILE_STORE_CONTAINER_NAME"
  value       = module.storage.container_name
}

output "postgres_host" {
  description = "Private hostname of the database server"
  value       = module.postgres.fqdn
}

output "postgres_port" {
  description = "Database port"
  value       = module.postgres.port
}

output "postgres_db_name" {
  description = "Database name"
  value       = module.postgres.db_name
}

output "postgres_username" {
  description = "Administrator login"
  value       = module.postgres.username
  sensitive   = true
}

output "redis_host" {
  description = "Hostname of the cache. Behind its private endpoint this resolves to a private address."
  value       = one(module.redis[*].hostname)
}

output "redis_ssl_port" {
  description = "TLS port of the cache. The plaintext port is disabled."
  value       = one(module.redis[*].ssl_port)
}

# Azure generates this rather than accepting one, so it comes out of the module
# rather than going in.
output "redis_primary_access_key" {
  description = "Generated primary access key for the cache"
  value       = one(module.redis[*].primary_access_key)
  sensitive   = true
}

# Only reflects a NAT gateway this module created. With a supplied network the
# cluster may still egress through one, but the module cannot see it, so this
# is empty rather than wrong.
output "nat_gateway_public_ips" {
  description = "Egress addresses of a NAT gateway this module created, which downstream allowlists key off. Empty when create_virtual_network is false, even if the supplied subnet has a NAT gateway of its own."
  value       = local.nat_gateway_ips
}

output "waf_policy_id" {
  description = "WAF policy to attach to an Application Gateway or Front Door route, null when disabled"
  value       = try(module.waf[0].policy_id, null)
}

# --- Cluster credentials -----------------------------------------------------
# The composition creates Kubernetes objects, so the root module has to be able
# to configure the kubernetes provider against the cluster it just made.

output "cluster_host" {
  description = "API server address for the kubernetes and helm providers"
  value       = module.aks.host
  sensitive   = true
}

output "cluster_ca_certificate" {
  description = "Cluster CA certificate, base64 encoded"
  value       = module.aks.cluster_ca_certificate
  sensitive   = true
}

output "client_certificate" {
  description = "Client certificate, base64 encoded. Empty when only Entra ID logins are accepted."
  value       = module.aks.client_certificate
  sensitive   = true
}

output "client_key" {
  description = "Client key, base64 encoded. Empty when only Entra ID logins are accepted."
  value       = module.aks.client_key
  sensitive   = true
}
