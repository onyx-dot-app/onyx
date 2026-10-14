locals {
  # Subnets opt in to the NAT gateway individually. A delegated database subnet
  # and the Application Gateway subnet must stay off it.
  nat_gateway_subnets = var.enable_nat_gateway ? {
    for key, subnet in var.subnets : key => subnet if subnet.nat_gateway
  } : {}
}

resource "azurerm_virtual_network" "this" {
  name                = "${var.name}-vnet"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = var.address_space
  tags                = var.tags
}

resource "azurerm_subnet" "this" {
  for_each = var.subnets

  name                              = "${var.name}-${each.key}"
  resource_group_name               = var.resource_group_name
  virtual_network_name              = azurerm_virtual_network.this.name
  address_prefixes                  = each.value.address_prefixes
  service_endpoints                 = each.value.service_endpoints
  private_endpoint_network_policies = each.value.private_endpoint_network_policies

  dynamic "delegation" {
    for_each = each.value.delegation != null ? [each.value.delegation] : []
    content {
      name = "delegation"
      service_delegation {
        name    = delegation.value
        actions = each.value.delegation_actions
      }
    }
  }
}

# A single public IP keeps egress on one address, so downstream allowlists stay
# stable across node replacements. Standard SKU is required by NAT gateway.
resource "azurerm_public_ip" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  name                = "${var.name}-nat-pip"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = var.nat_gateway_zones
  tags                = var.tags
}

resource "azurerm_nat_gateway" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  name                    = "${var.name}-nat"
  resource_group_name     = var.resource_group_name
  location                = var.location
  sku_name                = "Standard"
  idle_timeout_in_minutes = var.nat_gateway_idle_timeout_minutes
  zones                   = var.nat_gateway_zones
  tags                    = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  nat_gateway_id       = azurerm_nat_gateway.this[0].id
  public_ip_address_id = azurerm_public_ip.nat[0].id
}

resource "azurerm_subnet_nat_gateway_association" "this" {
  for_each = local.nat_gateway_subnets

  subnet_id      = azurerm_subnet.this[each.key].id
  nat_gateway_id = azurerm_nat_gateway.this[0].id

  # Without this the association can be created before the gateway has its
  # public IP, and egress silently falls back to the default outbound path.
  depends_on = [azurerm_nat_gateway_public_ip_association.this]
}

resource "azurerm_network_watcher_flow_log" "this" {
  count = var.enable_flow_logs ? 1 : 0

  name                 = "${var.name}-vnet-flow-log"
  network_watcher_name = var.network_watcher_name
  resource_group_name  = var.network_watcher_resource_group_name
  location             = var.location
  target_resource_id   = azurerm_virtual_network.this.id
  storage_account_id   = var.flow_log_storage_account_id
  enabled              = true
  version              = 2
  tags                 = var.tags

  retention_policy {
    enabled = var.flow_log_retention_days > 0
    days    = var.flow_log_retention_days
  }
}
