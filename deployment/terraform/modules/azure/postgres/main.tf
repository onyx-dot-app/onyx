locals {
  create_private_dns_zone = var.private_dns_zone_id == null
  private_dns_zone_id     = local.create_private_dns_zone ? azurerm_private_dns_zone.this[0].id : var.private_dns_zone_id

  password_auth_enabled = !var.entra_authentication_only

  # Alerts share one evaluation shape, chosen to match the AWS modules: sample
  # every 5 minutes over a 15-minute window, so a single spike does not page.
  alert_frequency   = "PT5M"
  alert_window_size = "PT15M"
  metric_namespace  = "Microsoft.DBforPostgreSQL/flexibleServers"
}

# A server joined to a virtual network resolves only through a private DNS
# zone, and Azure requires the zone name to end in this suffix.
resource "azurerm_private_dns_zone" "this" {
  count = local.create_private_dns_zone ? 1 : 0

  name                = "${var.name}.private.postgres.database.azure.com"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "this" {
  count = local.create_private_dns_zone ? 1 : 0

  name                  = "${var.name}-dns-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.this[0].name
  virtual_network_id    = var.virtual_network_id
  registration_enabled  = false
  tags                  = var.tags
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  version             = var.engine_version
  sku_name            = var.sku_name
  zone                = var.zone

  storage_mb        = var.storage_gb * 1024
  storage_tier      = var.storage_tier
  auto_grow_enabled = var.auto_grow_enabled

  # Joining the delegated subnet is what keeps the server off the public
  # internet. Stating it outright as well means the server never depends on
  # Azure defaulting the flag the way we expect.
  public_network_access_enabled = false
  delegated_subnet_id           = var.delegated_subnet_id
  private_dns_zone_id           = local.private_dns_zone_id

  administrator_login    = local.password_auth_enabled ? var.username : null
  administrator_password = local.password_auth_enabled ? var.password : null

  backup_retention_days        = var.backup_retention_days
  geo_redundant_backup_enabled = var.geo_redundant_backup_enabled

  dynamic "authentication" {
    for_each = var.enable_entra_authentication ? [1] : []
    content {
      active_directory_auth_enabled = true
      password_auth_enabled         = local.password_auth_enabled
      tenant_id                     = var.tenant_id
    }
  }

  dynamic "high_availability" {
    for_each = var.high_availability_enabled ? [1] : []
    content {
      mode = var.high_availability_mode
    }
  }

  dynamic "maintenance_window" {
    for_each = var.maintenance_window != null ? [var.maintenance_window] : []
    content {
      day_of_week  = maintenance_window.value.day_of_week
      start_hour   = maintenance_window.value.start_hour
      start_minute = maintenance_window.value.start_minute
    }
  }

  tags = var.tags

  # Guardrail, same as the AWS postgres module: this server holds production
  # data. A change Azure cannot make in place fails here rather than silently
  # replacing the server with an empty one. A real migration is done
  # deliberately with this guard removed.
  lifecycle {
    prevent_destroy = true

    # Azure hands back the zone it picked, and the standby's zone with it.
    # Neither can be changed without moving the server, so an unset variable
    # must not read as "move it back".
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.this]
}

# Without this an Entra-only server has no administrator: password logins are
# off and no Entra principal has been granted access, so nobody can connect to
# bootstrap the roles a workload identity needs.
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "this" {
  count = var.enable_entra_authentication && var.entra_administrator_object_id != null ? 1 : 0

  server_name         = azurerm_postgresql_flexible_server.this.name
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  object_id           = var.entra_administrator_object_id
  principal_name      = var.entra_administrator_principal_name
  principal_type      = var.entra_administrator_principal_type
}

resource "azurerm_postgresql_flexible_server_database" "this" {
  name      = var.db_name
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"

  # Dropping the database drops everything in it, and Azure gives no way back.
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_metric_alert" "cpu" {
  name                = "${var.name}-cpu-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "PostgreSQL ${var.name} CPU utilisation high"
  severity            = 2
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "cpu_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.cpu_alarm_threshold
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

resource "azurerm_monitor_metric_alert" "memory" {
  name                = "${var.name}-memory-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "PostgreSQL ${var.name} memory utilisation high"
  severity            = 2
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "memory_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.memory_alarm_threshold
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

# A full data volume wedges the writer. Auto-grow usually gets there first, but
# it stops at the largest size Azure offers.
resource "azurerm_monitor_metric_alert" "storage" {
  name                = "${var.name}-storage-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "PostgreSQL ${var.name} storage nearly full"
  severity            = 1
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "storage_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.storage_alarm_threshold
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

# A task holding a session across an external call, or a request-cancel leak,
# saturates the pool and new pods then fail to start.
resource "azurerm_monitor_metric_alert" "connections" {
  name                = "${var.name}-connections-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "PostgreSQL ${var.name} connection count high"
  severity            = 2
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "active_connections"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.connections_alarm_threshold
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

resource "azurerm_monitor_metric_alert" "iops" {
  name                = "${var.name}-iops-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "PostgreSQL ${var.name} consuming most of its provisioned IOPS"
  severity            = 2
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "disk_iops_consumed_percentage"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.iops_alarm_threshold
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}
