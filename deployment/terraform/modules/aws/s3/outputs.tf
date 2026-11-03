output "bucket_id" {
  value = aws_s3_bucket.this.id
}

output "bucket_arn" {
  value = aws_s3_bucket.this.arn
}

output "bucket_name" {
  value = aws_s3_bucket.this.bucket
}

output "bucket_regional_domain_name" {
  value = aws_s3_bucket.this.bucket_regional_domain_name
}

output "kms_key_arn" {
  description = "ARN of the KMS key the bucket encrypts with. Null when the bucket uses the AWS-managed key."
  value       = local.kms_key_id
}
