output "cache_id" {
  description = "Resource ID of the cache"
  value       = azurerm_managed_redis.this.id
}

output "hostname" {
  description = "Hostname of the cache. Behind a private endpoint this resolves to a private address from networks linked to the DNS zone."
  value       = azurerm_managed_redis.this.hostname
}

# Managed Redis speaks TLS on 10000, where Azure Cache for Redis used 6380.
output "ssl_port" {
  description = "TLS port. Managed Redis offers no plaintext port."
  value       = 10000
}

# Azure generates the keys and offers no way to set them, so the credential
# comes back out of the module rather than going in. They live on the database
# rather than the cluster, hence the enterprise data source.
output "primary_access_key" {
  description = "Generated primary access key, null when access keys are disabled"
  value       = try(data.azurerm_redis_enterprise_database.this[0].primary_access_key, null)
  sensitive   = true
}

output "secondary_access_key" {
  description = "Generated secondary access key, for rotating without downtime"
  value       = try(data.azurerm_redis_enterprise_database.this[0].secondary_access_key, null)
  sensitive   = true
}

output "private_dns_zone_id" {
  description = "Resource ID of the private DNS zone the cache resolves through, null when no private endpoint is used"
  value       = local.private_dns_zone_id
}
