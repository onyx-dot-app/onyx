locals {
  create_private_dns_zone = var.enable_private_endpoint && var.private_dns_zone_id == null
  private_dns_zone_id     = local.create_private_dns_zone ? azurerm_private_dns_zone.this[0].id : var.private_dns_zone_id

  # A cache behind a private endpoint has no reason to answer on its public
  # hostname, so that is the default unless the caller says otherwise.
  public_network_access_enabled = var.public_network_access_enabled != null ? var.public_network_access_enabled : !var.enable_private_endpoint

  alert_frequency   = "PT5M"
  alert_window_size = "PT15M"
  # Managed Redis is Redis Enterprise underneath, and reports under that
  # namespace rather than the Microsoft.Cache/redis one the retiring service used.
  metric_namespace = "Microsoft.Cache/redisEnterprise"

  # Managed Redis speaks TLS on 10000. There is no plaintext port to disable.
  port = 10000
}

# Azure stopped accepting new Azure Cache for Redis instances -- a create now
# returns "Azure Cache for Redis is retiring, create Azure Managed Redis
# instance instead" -- so this is the managed service rather than azurerm_redis_cache.
resource "azurerm_managed_redis" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location

  sku_name                  = var.sku_name
  high_availability_enabled = var.high_availability_enabled
  public_network_access     = local.public_network_access_enabled ? "Enabled" : "Disabled"

  default_database {
    access_keys_authentication_enabled = var.access_keys_enabled
    # Not a variable. The service this replaced had no plaintext port to turn
    # on, and offering one here would be a weaker guarantee than the module it
    # replaced, not a new feature.
    client_protocol   = "Encrypted"
    clustering_policy = var.clustering_policy
    eviction_policy   = var.eviction_policy
  }

  tags = var.tags
}

# The cache resource exposes only its hostname. Managed Redis is Redis
# Enterprise underneath, and the generated keys live on the database rather than
# the cluster, so they are read back through the enterprise data source.
#
# azurerm marks this deprecated in favour of azurerm_managed_redis_database,
# which does not exist yet: 4.81.0 is the latest 4.x and does not ship it. Swap
# when it lands; the deprecated name works until provider v5.
data "azurerm_redis_enterprise_database" "this" {
  count = var.access_keys_enabled ? 1 : 0

  name       = "default"
  cluster_id = azurerm_managed_redis.this.id
}

resource "azurerm_private_dns_zone" "this" {
  count = local.create_private_dns_zone ? 1 : 0

  name                = "privatelink.redis.azure.net"
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
    private_connection_resource_id = azurerm_managed_redis.this.id
    subresource_names              = ["redisEnterprise"]
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
  scopes              = [azurerm_managed_redis.this.id]
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
  scopes              = [azurerm_managed_redis.this.id]
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

resource "azurerm_monitor_metric_alert" "cpu" {
  name                = "${var.name}-cpu-high"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_managed_redis.this.id]
  description         = "Redis ${var.name} processor time high"
  severity            = 2
  frequency           = local.alert_frequency
  window_size         = local.alert_window_size
  tags                = var.tags

  criteria {
    metric_namespace = local.metric_namespace
    metric_name      = "percentProcessorTime"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.cpu_threshold_percent
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
  scopes              = [azurerm_managed_redis.this.id]
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
