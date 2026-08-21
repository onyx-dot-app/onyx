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
  description = "Subnet resource IDs, keyed by the same names as the subnets variable. Available once any NAT gateway associations exist, so a consumer that needs egress in place does not race them."
  value       = { for key, subnet in azurerm_subnet.this : key => subnet.id }

  depends_on = [azurerm_subnet_nat_gateway_association.this]
}

output "subnet_address_prefixes" {
  description = "Subnet address prefixes, keyed by the same names as the subnets variable"
  value       = { for key, subnet in azurerm_subnet.this : key => subnet.address_prefixes }
}

# Convenience outputs for the subnets the other modules expect. Null when the
# caller replaced the default subnet map and dropped that key.
#
# The AKS one waits on the NAT gateway associations. A cluster created with
# outbound_type = userAssignedNATGateway is rejected outright if its subnet has
# no gateway attached yet, and nothing else orders the two: the cluster depends
# on the subnet, the association depends on the subnet, so Terraform is free to
# run them at the same time. Making the id itself arrive late is what serialises
# them, and it does so for every consumer rather than asking each one to
# remember a depends_on.
output "aks_subnet_id" {
  description = "Resource ID of the AKS subnet, available once any NAT gateway association on it exists"
  value       = try(azurerm_subnet.this["aks"].id, null)

  depends_on = [azurerm_subnet_nat_gateway_association.this]
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
