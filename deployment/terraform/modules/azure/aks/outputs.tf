output "cluster_id" {
  description = "Resource ID of the cluster"
  value       = azurerm_kubernetes_cluster.this.id
}

output "cluster_name" {
  description = "Name of the cluster"
  value       = azurerm_kubernetes_cluster.this.name
}

# A private cluster leaves fqdn empty and publishes private_fqdn instead, so
# taking only the first returns nothing usable for the private case.
output "cluster_fqdn" {
  description = "API server hostname. For a private cluster this is the private name, which resolves only from inside the network."
  value       = coalesce(azurerm_kubernetes_cluster.this.fqdn, azurerm_kubernetes_cluster.this.private_fqdn)
}

# The trust anchor for federated credentials, the same role the OIDC provider
# plays for IRSA on AWS.
output "oidc_issuer_url" {
  description = "OIDC issuer URL of the cluster"
  value       = azurerm_kubernetes_cluster.this.oidc_issuer_url
}

output "node_resource_group" {
  description = "Resource group AKS creates for the cluster's own infrastructure. Node disks and load balancers land here, not in the cluster's resource group."
  value       = azurerm_kubernetes_cluster.this.node_resource_group
}

output "cluster_identity_principal_id" {
  description = "Principal ID of the cluster's own identity. Grant it Network Contributor on a public IP or subnet held outside the node resource group, or the load balancer cannot attach it."
  value       = try(azurerm_kubernetes_cluster.this.identity[0].principal_id, null)
}

output "kubelet_identity_object_id" {
  description = "Object ID of the kubelet identity, for granting nodes access to a container registry"
  value       = try(azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id, null)
}

output "workload_identity_client_id" {
  description = "Client ID of the workload identity, which annotates the service account. Pods must also carry the azure.workload.identity/use label, which this module cannot set for them: without it the webhook projects no token. Null when no storage account was supplied."
  value       = try(azurerm_user_assigned_identity.workload[0].client_id, null)
}

output "workload_identity_principal_id" {
  description = "Principal ID of the workload identity, for granting it further roles"
  value       = try(azurerm_user_assigned_identity.workload[0].principal_id, null)
}

output "workload_service_account_subjects" {
  description = "Kubernetes service account subjects the workload identity trusts"
  value       = local.workload_identity_enabled ? values(local.workload_service_account_subjects) : []
}

output "node_pool_names" {
  description = "Names of every node pool on the cluster, including the system pool"
  value       = concat(["main"], sort(keys(local.additional_node_pools)))
}

output "kube_config_raw" {
  description = "kubeconfig for the cluster"
  value       = azurerm_kubernetes_cluster.this.kube_config_raw
  sensitive   = true
}

output "host" {
  description = "API server address, for configuring the kubernetes and helm providers"
  value       = try(azurerm_kubernetes_cluster.this.kube_config[0].host, null)
  sensitive   = true
}

output "cluster_ca_certificate" {
  description = "Cluster CA certificate, base64 encoded, for configuring the kubernetes and helm providers"
  value       = try(azurerm_kubernetes_cluster.this.kube_config[0].cluster_ca_certificate, null)
  sensitive   = true
}

# This module creates Kubernetes objects, so whoever calls it has to be able to
# configure the kubernetes provider against the cluster it just made. These are
# the remaining pieces that takes.
output "client_certificate" {
  description = "Client certificate, base64 encoded. Empty when local accounts are disabled and only Entra ID logins are accepted."
  value       = try(azurerm_kubernetes_cluster.this.kube_config[0].client_certificate, null)
  sensitive   = true
}

output "client_key" {
  description = "Client key, base64 encoded. Empty when local accounts are disabled and only Entra ID logins are accepted."
  value       = try(azurerm_kubernetes_cluster.this.kube_config[0].client_key, null)
  sensitive   = true
}
