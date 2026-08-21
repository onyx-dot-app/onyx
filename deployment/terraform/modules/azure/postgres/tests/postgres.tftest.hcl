# Plans the module against a mocked provider, so these run without an Azure
# subscription or credentials. Run with `terraform test` from the module directory.

mock_provider "azurerm" {}

variables {
  name                = "onyx-postgres-prod"
  resource_group_name = "onyx-rg"
  location            = "eastus"
  delegated_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet/subnets/onyx-postgres"
  virtual_network_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet"
  password            = "not-a-real-password"
}

run "defaults" {
  command = plan

  assert {
    condition     = azurerm_postgresql_flexible_server.this.storage_mb == 131072
    error_message = "storage_gb should be converted to the MB the provider wants."
  }

  assert {
    condition     = azurerm_private_dns_zone.this[0].name == "onyx-postgres-prod.private.postgres.database.azure.com"
    error_message = "Azure requires the private DNS zone name to end in .private.postgres.database.azure.com."
  }

  assert {
    condition     = azurerm_postgresql_flexible_server.this.delegated_subnet_id != null
    error_message = "The server must join the delegated subnet so it has no public endpoint."
  }

  assert {
    condition     = length(azurerm_postgresql_flexible_server.this.high_availability) == 0
    error_message = "High availability is opt-in because it roughly doubles cost."
  }

  assert {
    condition     = length(azurerm_postgresql_flexible_server.this.authentication) == 0
    error_message = "Entra ID authentication is opt-in, matching the AWS module's IAM auth."
  }

  assert {
    condition     = azurerm_postgresql_flexible_server.this.administrator_login == "psqladmin"
    error_message = "Password authentication is on by default, so the admin login should be set."
  }
}

run "all_five_alerts_exist_and_stay_silent" {
  command = plan

  assert {
    condition     = length(azurerm_monitor_metric_alert.cpu.action) == 0
    error_message = "With no action group the alerts must exist but notify nothing, the same as the AWS modules."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.storage.criteria[0].metric_name == "storage_percent"
    error_message = "The AWS module's free-storage floor maps onto Azure's percent-used metric."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.storage.severity == 1
    error_message = "A full data volume wedges the writer, so it should outrank the other alerts."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.iops.criteria[0].metric_name == "disk_iops_consumed_percentage"
    error_message = "IOPS should alert against the provisioned limit, not an absolute count."
  }
}

run "an_action_group_wires_every_alert" {
  command = plan

  variables {
    action_group_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Insights/actionGroups/onyx-pager"]
  }

  assert {
    condition = alltrue([
      length(azurerm_monitor_metric_alert.cpu.action) == 1,
      length(azurerm_monitor_metric_alert.memory.action) == 1,
      length(azurerm_monitor_metric_alert.storage.action) == 1,
      length(azurerm_monitor_metric_alert.connections.action) == 1,
      length(azurerm_monitor_metric_alert.iops.action) == 1,
    ])
    error_message = "Every alert should route to the supplied action group."
  }
}

run "entra_only_drops_the_password_login" {
  command = plan

  variables {
    enable_entra_authentication        = true
    entra_authentication_only          = true
    tenant_id                          = "00000000-0000-0000-0000-000000000000"
    password                           = null
    entra_administrator_object_id      = "11111111-1111-1111-1111-111111111111"
    entra_administrator_principal_name = "onyx-db-admins"
    entra_administrator_principal_type = "Group"
  }

  assert {
    condition     = length(azurerm_postgresql_flexible_server_active_directory_administrator.this) == 1
    error_message = "An Entra-only server needs an Entra administrator, or nobody can connect to it."
  }

  # administrator_login is Optional+Computed, so a null reads as unknown until
  # apply. The authentication block below is what actually turns password
  # logins off, and it is knowable at plan time.
  assert {
    condition     = one(azurerm_postgresql_flexible_server.this.authentication).password_auth_enabled == false
    error_message = "entra_authentication_only must turn password authentication off on the server."
  }

  assert {
    condition     = one(azurerm_postgresql_flexible_server.this.authentication).active_directory_auth_enabled == true
    error_message = "Entra ID authentication should be on."
  }
}

run "high_availability_is_zone_redundant" {
  command = plan

  variables {
    high_availability_enabled = true
  }

  assert {
    condition     = one(azurerm_postgresql_flexible_server.this.high_availability).mode == "ZoneRedundant"
    error_message = "The standby should default to a second zone."
  }
}

run "an_existing_dns_zone_is_reused" {
  command = plan

  variables {
    private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/privateDnsZones/existing.private.postgres.database.azure.com"
  }

  assert {
    condition     = length(azurerm_private_dns_zone.this) == 0
    error_message = "Supplying a zone must not create a second one."
  }

  assert {
    condition     = length(azurerm_private_dns_zone_virtual_network_link.this) == 0
    error_message = "The caller owns the link for a zone they supplied."
  }
}

run "no_entra_administrator_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_postgresql_flexible_server_active_directory_administrator.this) == 0
    error_message = "A password-authenticated server needs no Entra administrator."
  }
}

run "rejects_a_server_that_would_have_no_password" {
  command = plan

  variables {
    password = null
  }

  expect_failures = [var.password]
}

run "rejects_entra_only_with_nobody_able_to_log_in" {
  command = plan

  variables {
    enable_entra_authentication = true
    entra_authentication_only   = true
    tenant_id                   = "00000000-0000-0000-0000-000000000000"
    password                    = null
  }

  expect_failures = [var.entra_authentication_only]
}

run "rejects_a_half_specified_entra_administrator" {
  command = plan

  variables {
    enable_entra_authentication   = true
    tenant_id                     = "00000000-0000-0000-0000-000000000000"
    entra_administrator_object_id = "11111111-1111-1111-1111-111111111111"
  }

  expect_failures = [var.entra_administrator_principal_name]
}

run "accepts_a_storage_tier_azure_offers" {
  command = plan

  variables {
    storage_tier = "P30"
  }

  assert {
    condition     = azurerm_postgresql_flexible_server.this.storage_tier == "P30"
    error_message = "A valid tier should reach the server."
  }
}

run "rejects_a_storage_tier_azure_does_not_offer" {
  command = plan

  variables {
    storage_tier = "P12"
  }

  expect_failures = [var.storage_tier]
}

run "the_server_states_that_it_has_no_public_endpoint" {
  command = plan

  assert {
    condition     = azurerm_postgresql_flexible_server.this.public_network_access_enabled == false
    error_message = "The server should never depend on Azure defaulting this flag the way we expect."
  }
}

run "a_tier_can_be_raised_at_the_largest_sizes" {
  command = plan

  # Raising the tier to buy IOPS is the documented feature, and it applies at
  # the top of the range too.
  variables {
    storage_gb   = 8192
    storage_tier = "P70"
  }

  assert {
    condition     = azurerm_postgresql_flexible_server.this.storage_tier == "P70"
    error_message = "A raised tier should reach the server rather than being refused."
  }
}

run "rejects_a_tier_below_the_size_default" {
  command = plan

  variables {
    storage_gb   = 512
    storage_tier = "P10"
  }

  expect_failures = [var.storage_tier]
}

run "accepts_the_high_tier_at_the_size_that_carries_it" {
  command = plan

  variables {
    storage_gb   = 8192
    storage_tier = "P60"
  }

  assert {
    condition     = azurerm_postgresql_flexible_server.this.storage_tier == "P60"
    error_message = "P60 is the tier the 8192 GiB volume carries."
  }
}

run "rejects_backup_retention_below_the_flexible_server_floor" {
  command = plan

  variables {
    backup_retention_days = 3
  }

  expect_failures = [var.backup_retention_days]
}

run "rejects_a_storage_size_azure_does_not_offer" {
  command = plan

  variables {
    storage_gb = 100
  }

  expect_failures = [var.storage_gb]
}

run "rejects_high_availability_on_a_burstable_sku" {
  command = plan

  variables {
    sku_name                  = "B_Standard_B2s"
    high_availability_enabled = true
  }

  expect_failures = [var.high_availability_enabled]
}

run "rejects_entra_only_without_entra" {
  command = plan

  # password is cleared so the only rule left to break is the one this run is
  # about, rather than the unrelated "password would be discarded" rule.
  variables {
    entra_authentication_only = true
    password                  = null
  }

  expect_failures = [var.entra_authentication_only]
}

run "rejects_a_password_that_would_be_discarded" {
  command = plan

  # The administrator is supplied so that the only rule left to break is the
  # one about the password.
  variables {
    enable_entra_authentication        = true
    entra_authentication_only          = true
    tenant_id                          = "00000000-0000-0000-0000-000000000000"
    password                           = "not-a-real-password"
    entra_administrator_object_id      = "11111111-1111-1111-1111-111111111111"
    entra_administrator_principal_name = "onyx-db-admins"
    entra_administrator_principal_type = "Group"
  }

  expect_failures = [var.password]
}

run "rejects_entra_without_a_tenant" {
  command = plan

  variables {
    enable_entra_authentication = true
  }

  expect_failures = [var.tenant_id]
}

run "rejects_backup_retention_azure_would_reject" {
  command = plan

  variables {
    backup_retention_days = 0
  }

  expect_failures = [var.backup_retention_days]
}
