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

output "opensearch_endpoint" {
  description = "OpenSearch domain endpoint"
  value       = var.enable_opensearch ? module.opensearch[0].domain_endpoint : null
}

output "opensearch_dashboard_endpoint" {
  description = "OpenSearch Dashboards endpoint"
  value       = var.enable_opensearch ? module.opensearch[0].kibana_endpoint : null
}

output "opensearch_domain_arn" {
  description = "OpenSearch domain ARN"
  value       = var.enable_opensearch ? module.opensearch[0].domain_arn : null
}
