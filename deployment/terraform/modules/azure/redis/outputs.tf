output "cache_id" {
  description = "Resource ID of the cache"
  value       = azurerm_redis_cache.this.id
}

output "hostname" {
  description = "Hostname of the cache. Behind a private endpoint this resolves to a private address from networks linked to the DNS zone."
  value       = azurerm_redis_cache.this.hostname
}

output "ssl_port" {
  description = "TLS port. The non-TLS port is disabled."
  value       = azurerm_redis_cache.this.ssl_port
}

# The AWS module takes an auth token as an input; Azure generates the keys and
# offers no way to set them, so the credential comes back out of the module.
output "primary_access_key" {
  description = "Generated primary access key, null when access keys are disabled"
  value       = var.access_keys_enabled ? azurerm_redis_cache.this.primary_access_key : null
  sensitive   = true
}

output "secondary_access_key" {
  description = "Generated secondary access key, for rotating without downtime"
  value       = var.access_keys_enabled ? azurerm_redis_cache.this.secondary_access_key : null
  sensitive   = true
}

output "private_dns_zone_id" {
  description = "Resource ID of the private DNS zone the cache resolves through, null when no private endpoint is used"
  value       = local.private_dns_zone_id
}
