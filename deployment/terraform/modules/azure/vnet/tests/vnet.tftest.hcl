# Plans the module against a mocked provider, so these run without an Azure
# subscription or credentials. Run with `terraform test` from the module directory.

mock_provider "azurerm" {}

variables {
  name                = "onyx"
  resource_group_name = "onyx-rg"
  location            = "eastus"
}

run "default_subnets" {
  command = plan

  assert {
    condition     = length(azurerm_subnet.this) == 4
    error_message = "The default subnet map should create four subnets."
  }

  assert {
    condition     = azurerm_subnet.this["aks"].name == "onyx-aks"
    error_message = "Subnet names should be prefixed with the module name."
  }

  assert {
    condition     = contains(azurerm_subnet.this["aks"].service_endpoints, "Microsoft.Storage")
    error_message = "The AKS subnet needs the Microsoft.Storage service endpoint so the storage account can restrict access to it."
  }

  assert {
    condition     = one(azurerm_subnet.this["postgres"].delegation).service_delegation[0].name == "Microsoft.DBforPostgreSQL/flexibleServers"
    error_message = "The postgres subnet must be delegated to PostgreSQL Flexible Server."
  }

  assert {
    condition     = length(azurerm_subnet.this["aks"].delegation) == 0
    error_message = "Only the postgres subnet should be delegated."
  }
}

run "nat_gateway_attaches_only_to_opted_in_subnets" {
  command = plan

  assert {
    condition     = length(azurerm_subnet_nat_gateway_association.this) == 1
    error_message = "Only the AKS subnet opts into the NAT gateway by default."
  }

  assert {
    condition     = contains(keys(azurerm_subnet_nat_gateway_association.this), "aks")
    error_message = "The AKS subnet is the one that needs egress."
  }

  assert {
    condition     = azurerm_public_ip.nat[0].sku == "Standard"
    error_message = "A NAT gateway requires a Standard SKU public IP."
  }
}

run "nat_gateway_can_be_disabled" {
  command = plan

  variables {
    enable_nat_gateway = false
  }

  assert {
    condition     = length(azurerm_nat_gateway.this) == 0
    error_message = "enable_nat_gateway = false should create no NAT gateway."
  }

  assert {
    condition     = length(azurerm_subnet_nat_gateway_association.this) == 0
    error_message = "Disabling the NAT gateway must also drop its subnet associations."
  }
}

run "flow_logs_off_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_network_watcher_flow_log.this) == 0
    error_message = "Flow logs are opt-in because they need a storage account and a Network Watcher."
  }
}

run "flow_logs_require_a_storage_account" {
  command = plan

  variables {
    enable_flow_logs = true
  }

  expect_failures = [var.enable_flow_logs]
}

run "flow_logs_require_a_network_watcher_too" {
  command = plan

  variables {
    enable_flow_logs            = true
    flow_log_storage_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxflowlogs"
  }

  expect_failures = [var.enable_flow_logs]
}

run "flow_logs_plan_when_both_destination_and_watcher_are_set" {
  command = plan

  variables {
    enable_flow_logs            = true
    flow_log_storage_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxflowlogs"
    network_watcher_name        = "NetworkWatcher_eastus"
  }

  assert {
    condition     = length(azurerm_network_watcher_flow_log.this) == 1
    error_message = "With a destination and a watcher the flow log should be created."
  }

  assert {
    condition     = azurerm_network_watcher_flow_log.this[0].network_watcher_name == "NetworkWatcher_eastus"
    error_message = "The flow log should be owned by the supplied Network Watcher."
  }

  assert {
    condition     = one(azurerm_network_watcher_flow_log.this[0].retention_policy).days == 365
    error_message = "Retention should default to the Azure ceiling of 365 days."
  }
}

run "a_custom_subnet_map_gets_no_nat_gateway_unless_it_asks" {
  command = plan

  # Opt-in: a caller writing their own map should not silently attach a NAT
  # gateway to a subnet that cannot carry one.
  variables {
    subnets = {
      aks = {
        address_prefixes = ["10.0.0.0/20"]
      }
      appgw = {
        address_prefixes = ["10.0.18.0/24"]
      }
    }
  }

  assert {
    condition     = length(azurerm_subnet_nat_gateway_association.this) == 0
    error_message = "A custom subnet map should attach no NAT gateway until a subnet asks for one."
  }
}

run "rejects_a_blank_network_watcher_name" {
  command = plan

  variables {
    enable_flow_logs            = true
    flow_log_storage_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxflowlogs"
    network_watcher_name        = "   "
  }

  expect_failures = [var.enable_flow_logs]
}

run "flow_log_retention_respects_the_azure_ceiling" {
  command = plan

  variables {
    flow_log_retention_days = 400
  }

  expect_failures = [var.flow_log_retention_days]
}

run "nat_gateway_is_regional_or_single_zone" {
  command = plan

  variables {
    nat_gateway_zones = ["1", "2"]
  }

  expect_failures = [var.nat_gateway_zones]
}

run "subnets_need_an_address_prefix" {
  command = plan

  variables {
    subnets = {
      aks = {
        address_prefixes = []
      }
    }
  }

  expect_failures = [var.subnets]
}
