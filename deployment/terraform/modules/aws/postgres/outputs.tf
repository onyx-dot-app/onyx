output "endpoint" {
  description = "RDS endpoint hostname"
  value       = aws_db_instance.this.endpoint
}

output "port" {
  description = "RDS port"
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Database name"
  value       = aws_db_instance.this.db_name
}

output "username" {
  description = "Master username"
  value       = aws_db_instance.this.username
  sensitive   = true
}

output "dbi_resource_id" {
  description = "DB instance resource ID used for IAM auth resource ARNs"
  value       = aws_db_instance.this.resource_id
}

output "address" {
  description = "RDS hostname without the port, for callers that build their own DSN"
  value       = aws_db_instance.this.address
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master password, null unless manage_master_user_password is set"
  value       = try(aws_db_instance.this.master_user_secret[0].secret_arn, null)
}
