output "redis_endpoint" {
  description = "The endpoint of the Redis cluster"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "redis_port" {
  description = "The port of the Redis cluster"
  value       = aws_elasticache_replication_group.redis.port
}

output "redis_ssl_enabled" {
  description = "Whether SSL/TLS is enabled for Redis"
  value       = var.transit_encryption_enabled
}
