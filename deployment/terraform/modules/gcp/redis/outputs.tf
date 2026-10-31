# Onyx reads these as REDIS_HOST, REDIS_PORT and REDIS_PASSWORD, and needs
# REDIS_SSL=true when redis_url_scheme is "rediss". It uses DB 0, 14 and 15 on
# this one endpoint; the database numbers are not outputs because they are
# Onyx defaults, not properties of the instance.

output "instance_id" {
  description = "Instance ID, as projects/<project>/locations/<region>/instances/<name>"
  value       = google_redis_instance.this.id
}

output "host" {
  description = "Private IP address of the primary endpoint. It stays the same across a STANDARD_HA failover."
  value       = google_redis_instance.this.host
}

output "port" {
  description = "6379 for plaintext, 6378 with transit encryption"
  value       = google_redis_instance.this.port
}

# Memorystore generates the AUTH string and offers no way to set it, so the
# credential comes out of the module rather than going in.
output "auth_string" {
  description = "Generated AUTH string, for REDIS_PASSWORD"
  value       = google_redis_instance.this.auth_string
  sensitive   = true
}

# Public CA certificates, not secrets. Clients should trust every entry so a
# CA rotation does not break TLS. Empty when transit encryption is off.
output "server_ca_certs" {
  description = "PEM server CA certificates to mount for REDIS_SSL_CA_CERTS"
  value       = [for c in google_redis_instance.this.server_ca_certs : c.cert]
}

output "current_location_id" {
  description = "Zone the primary is in now. On STANDARD_HA this changes after a failover."
  value       = google_redis_instance.this.current_location_id
}

output "redis_url_scheme" {
  description = "\"rediss\" with transit encryption, \"redis\" without"
  value       = var.transit_encryption_enabled ? "rediss" : "redis"
}
