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
  description = "ARN of the IAM role for workloads (S3 + RDS)"
  value       = local.workload_irsa_enabled ? module.irsa-workload-access[0].iam_role_arn : null
}

output "workload_irsa_service_account_subjects" {
  description = "Kubernetes service account subjects trusted by the workload IRSA role"
  value       = local.workload_irsa_enabled ? local.workload_irsa_service_account_subjects : []
}

output "cluster_security_group_id" {
  value = module.eks.cluster_security_group_id
}

output "node_security_group_id" {
  value = module.eks.node_security_group_id
}

output "oidc_provider" {
  description = "OIDC provider URL (no https://) for IRSA role trust policies"
  value       = module.eks.oidc_provider
}

output "oidc_provider_arn" {
  description = "OIDC provider ARN for IRSA role trust policies"
  value       = module.eks.oidc_provider_arn
}
