output "role_arn" {
  description = "IRSA role ARN to annotate the sandbox-file-sync ServiceAccount with."
  value       = aws_iam_role.sandbox_file_sync.arn
}

output "bucket_name" {
  description = "Sandbox S3 bucket name (set as SANDBOX_S3_BUCKET)."
  value       = var.bucket_name
}

output "bucket_arn" {
  description = "Sandbox S3 bucket ARN."
  value       = local.bucket_arn
}
