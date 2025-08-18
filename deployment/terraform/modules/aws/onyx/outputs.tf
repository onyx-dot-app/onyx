output "postgres_connection_url" {
  value     = module.postgres.connection_url
  sensitive = true
}

output "redis_connection_url" {
  value     = module.redis.redis_endpoint
  sensitive = true
}

output "cluster_name" {
  value = module.eks.cluster_name
}
