output "role_arn" {
  description = "IRSA role ARN to annotate the sandbox-file-sync ServiceAccount with."
  value       = aws_iam_role.sandbox_file_sync.arn
}

output "bucket_name" {
  description = "Sandbox S3 bucket name (set as SANDBOX_S3_BUCKET)."
  value       = aws_s3_bucket.sandbox.id
}

output "bucket_arn" {
  value = aws_s3_bucket.sandbox.arn
}
