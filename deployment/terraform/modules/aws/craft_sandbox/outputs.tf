output "role_arn" {
  description = "ARN of the IAM role. Set this as `craft.sandboxFileSyncRoleArn` in the Helm chart values."
  value       = aws_iam_role.sandbox.arn
}

output "bucket_name" {
  description = "Name of the sandbox S3 bucket. Set this as `configMap.SANDBOX_S3_BUCKET` in the Helm chart values."
  value       = aws_s3_bucket.sandbox.id
}

output "bucket_arn" {
  description = "ARN of the sandbox S3 bucket."
  value       = aws_s3_bucket.sandbox.arn
}
