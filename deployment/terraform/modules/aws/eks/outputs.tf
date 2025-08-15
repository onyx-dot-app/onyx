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

output "s3_access_role_arn" {
  description = "ARN of the IAM role for S3 access"
  value       = length(module.irsa-s3-access) > 0 ? module.irsa-s3-access[0].iam_role_arn : null
}
