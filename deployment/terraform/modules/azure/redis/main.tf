locals {
  create_private_dns_zone = var.enable_private_endpoint && var.private_dns_zone_id == null
  private_dns_zone_id     = local.create_private_dns_zone ? azurerm_private_dns_zone.this[0].id : var.private_dns_zone_id

  # A cache behind a private endpoint has no reason to answer on its public
  # hostname, so that is the default unless the caller says otherwise.
  public_network_access_enabled = var.public_network_access_enabled != null ? var.public_network_access_enabled : !var.enable_private_endpoint

  alert_frequency   = "PT5M"
  alert_window_size = "PT15M"
  metric_namespace  = "Microsoft.Cache/redis"
}

resource "azurerm_redis_cache" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location

  sku_name = var.sku_name
  family   = var.family
  capacity = var.capacity
  zones    = var.zones

  minimum_tls_version           = var.minimum_tls_version
  non_ssl_port_enabled          = false
  public_network_access_enabled = local.public_network_access_enabled

  access_keys_authentication_enabled = var.access_keys_enabled

  redis_configuration {
    maxmemory_policy                        = var.maxmemory_policy
    active_directory_authentication_enabled = var.enable_entra_authentication
  }

  tags = var.tags
}

resource "azurerm_private_dns_zone" "this" {
  count = local.create_private_dns_zone ? 1 : 0

  name                = "privatelink.redis.cache.windows.net"
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

resource "azurerm_private_endpoint" "this" {
  count = var.enable_private_endpoint ? 1 : 0

  name                = "${var.name}-pe"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoint_subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "${var.name}-psc"
    private_connection_resource_id = azurerm_redis_cache.this.id
    subresource_names              = ["redisCache"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [local.private_dns_zone_id]
  }
}

# Memory is the failure mode that actually takes a broker down: keys that never
# expire climb to the limit, eviction cannot free anything, and Redis starts
# rejecting writes, at which point the whole Celery fleet crashloops at once.
resource "azurerm_monitor_metric_alert" "memory_high" {
  name                = "${var.name}-memory-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_redis_cache.this.id]
  description         = "Redis ${var.name} memory usage high"
  severity            = 2
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "usedmemorypercentage"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.memory_high_threshold_percent
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

resource "azurerm_monitor_metric_alert" "memory_critical" {
  name                = "${var.name}-memory-critical"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_redis_cache.this.id]
  description         = "Redis ${var.name} memory usage critical, writes may be rejected"
  severity            = 1
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "usedmemorypercentage"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.memory_critical_threshold_percent
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

resource "azurerm_monitor_metric_alert" "server_load" {
  name                = "${var.name}-server-load-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_redis_cache.this.id]
  description         = "Redis ${var.name} server thread saturated"
  severity            = 2
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "serverLoad"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.server_load_threshold_percent
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

resource "azurerm_monitor_metric_alert" "evicted_keys" {
  name                = "${var.name}-evicted-keys"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_redis_cache.this.id]
  description         = "Redis ${var.name} is evicting keys, which for a Celery broker means dropped tasks"
  severity            = 1
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "evictedkeys"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = var.evicted_keys_threshold
  }

  dynamic "action" {
    for_each = var.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}
