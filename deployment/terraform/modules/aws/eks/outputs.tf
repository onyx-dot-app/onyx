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
  value       = length(module.irsa-workload-access) > 0 ? module.irsa-workload-access[0].iam_role_arn : null
}
