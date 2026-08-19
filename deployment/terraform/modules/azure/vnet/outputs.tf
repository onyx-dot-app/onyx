output "vnet_id" {
  description = "Resource ID of the virtual network"
  value       = azurerm_virtual_network.this.id
}

output "vnet_name" {
  description = "Name of the virtual network"
  value       = azurerm_virtual_network.this.name
}

output "address_space" {
  description = "Address space of the virtual network"
  value       = azurerm_virtual_network.this.address_space
}

output "subnet_ids" {
  description = "Subnet resource IDs, keyed by the same names as the subnets variable"
  value       = { for key, subnet in azurerm_subnet.this : key => subnet.id }
}

output "subnet_address_prefixes" {
  description = "Subnet address prefixes, keyed by the same names as the subnets variable"
  value       = { for key, subnet in azurerm_subnet.this : key => subnet.address_prefixes }
}

# Convenience outputs for the subnets the other modules expect. Null when the
# caller replaced the default subnet map and dropped that key.
output "aks_subnet_id" {
  description = "Resource ID of the AKS subnet"
  value       = try(azurerm_subnet.this["aks"].id, null)
}

output "postgres_subnet_id" {
  description = "Resource ID of the delegated PostgreSQL Flexible Server subnet"
  value       = try(azurerm_subnet.this["postgres"].id, null)
}

output "private_endpoint_subnet_id" {
  description = "Resource ID of the subnet that holds private endpoints"
  value       = try(azurerm_subnet.this["private_endpoints"].id, null)
}

output "app_gateway_subnet_id" {
  description = "Resource ID of the Application Gateway subnet"
  value       = try(azurerm_subnet.this["app_gateway"].id, null)
}

output "nat_gateway_id" {
  description = "Resource ID of the NAT gateway, null when disabled"
  value       = try(azurerm_nat_gateway.this[0].id, null)
}

output "nat_gateway_public_ips" {
  description = "Public IPs assigned to the NAT gateway. Egress from every attached subnet leaves from these."
  value       = var.enable_nat_gateway ? [azurerm_public_ip.nat[0].ip_address] : []
}
