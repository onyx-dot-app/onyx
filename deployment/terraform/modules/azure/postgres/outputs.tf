output "server_id" {
  description = "Resource ID of the flexible server"
  value       = azurerm_postgresql_flexible_server.this.id
}

output "server_name" {
  description = "Name of the flexible server"
  value       = azurerm_postgresql_flexible_server.this.name
}

output "fqdn" {
  description = "Private hostname of the server. Resolves only from networks linked to the private DNS zone."
  value       = azurerm_postgresql_flexible_server.this.fqdn
}

output "port" {
  description = "Port the server listens on"
  value       = 5432
}

# Reported from the variable rather than the resource, because a database the
# server ships is not one this module creates.
output "db_name" {
  description = "Name of the database Onyx connects to, whether this module created it or the server shipped it"
  value       = var.db_name
}

output "username" {
  description = "Administrator login, null when password authentication is off"
  value       = azurerm_postgresql_flexible_server.this.administrator_login
  sensitive   = true
}

output "private_dns_zone_id" {
  description = "Resource ID of the private DNS zone the server resolves through"
  value       = local.private_dns_zone_id
}

output "entra_administrator_object_id" {
  description = "Object ID of the Entra database administrator, null when none was configured"
  value       = try(azurerm_postgresql_flexible_server_active_directory_administrator.this[0].object_id, null)
}
