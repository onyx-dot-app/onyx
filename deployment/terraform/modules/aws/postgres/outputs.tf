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
