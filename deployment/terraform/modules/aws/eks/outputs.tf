output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  value     = module.eks.cluster_certificate_authority_data
  sensitive = true
}

output "workload_irsa_role_arn" {
  description = "ARN of the IAM role for workloads (S3 + optional RDS)"
  value       = local.workload_irsa_enabled ? module.irsa-workload-access[0].iam_role_arn : null
}

output "workload_irsa_service_account_subjects" {
  description = "Kubernetes service account subjects trusted by the workload IRSA role"
  value       = local.workload_irsa_enabled ? local.workload_irsa_service_account_subjects : []
}

output "node_security_group_id" {
  description = "Node security group ID from the EKS module"
  value       = module.eks.node_security_group_id
}

output "cluster_security_group_id" {
  description = "Cluster security group ID from the EKS module"
  value       = module.eks.cluster_security_group_id
}

# Re-exported from the upstream eks module so the craft_sandbox module can
# trust-scope its IRSA role to the cluster's OIDC provider.
output "oidc_provider_arn" {
  description = "EKS OIDC provider ARN (for IRSA roles)"
  value       = module.eks.oidc_provider_arn
}

output "oidc_provider" {
  description = "EKS OIDC issuer host/path (no https://)"
  value       = module.eks.oidc_provider
}
