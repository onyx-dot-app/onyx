output "redis_connection_url" {
  value     = module.redis.redis_endpoint
  sensitive = true
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "postgres_endpoint" {
  description = "RDS endpoint hostname"
  value       = module.postgres.endpoint
}

output "postgres_port" {
  description = "RDS port"
  value       = module.postgres.port
}

output "postgres_db_name" {
  description = "RDS database name"
  value       = module.postgres.db_name
}

output "postgres_username" {
  description = "RDS master username"
  value       = module.postgres.username
  sensitive   = true
}

output "postgres_dbi_resource_id" {
  description = "RDS DB instance resource id"
  value       = module.postgres.dbi_resource_id
}
