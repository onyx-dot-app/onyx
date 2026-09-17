# Plans the module against a mocked provider, so these run without an Azure
# subscription or credentials. Run with `terraform test` from the module directory.

mock_provider "azurerm" {}

variables {
  name                       = "onyx-redis-prod"
  resource_group_name        = "onyx-rg"
  location                   = "eastus2"
  private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet/subnets/onyx-private-endpoints"
  virtual_network_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet"
}

run "defaults_are_private_and_tls_only" {
  command = plan

  assert {
    condition     = one(azurerm_managed_redis.this.default_database).client_protocol == "Encrypted"
    error_message = "Managed Redis has no plaintext port, and the client protocol should say so."
  }

  assert {
    condition     = azurerm_managed_redis.this.public_network_access == "Disabled"
    error_message = "A cache behind a private endpoint has no reason to answer on its public hostname."
  }

  assert {
    condition     = length(azurerm_private_endpoint.this) == 1
    error_message = "The private endpoint should be created by default."
  }

  assert {
    condition     = one(azurerm_private_endpoint.this[0].private_service_connection).subresource_names[0] == "redisEnterprise"
    error_message = "Managed Redis is Redis Enterprise underneath, so that is the private endpoint subresource."
  }
}

run "a_plain_redis_client_can_talk_to_it" {
  command = plan

  # Both sharding policies fail with CROSSSLOT on Celery's first publish, so the
  # non-sharded policy is the only one Onyx runs on unchanged.
  assert {
    condition     = one(azurerm_managed_redis.this.default_database).clustering_policy == "NoCluster"
    error_message = "Onyx needs the non-sharded policy; a sharded one breaks Celery with CROSSSLOT."
  }
}

run "default_size" {
  command = plan

  assert {
    condition     = azurerm_managed_redis.this.sku_name == "Balanced_B5"
    error_message = "Balanced_B5 is about 5 GB, the closest shape to what the AWS module defaults to."
  }
}

run "four_alerts_exist_and_stay_silent" {
  command = plan

  assert {
    condition     = length(azurerm_monitor_metric_alert.memory_high.action) == 0
    error_message = "With no action group the alerts must exist but notify nothing."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.memory_high.criteria[0].metric_namespace == "Microsoft.Cache/redisEnterprise"
    error_message = "Managed Redis reports under the Redis Enterprise namespace, not the retiring service's."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.cpu.criteria[0].metric_name == "percentProcessorTime"
    error_message = "Redis Enterprise reports processor time rather than the single-thread server load the old service exposed."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.evicted_keys.criteria[0].aggregation == "Total"
    error_message = "Evictions are a count over the window, not an average."
  }
}

run "keys_are_read_off_the_database_not_the_cluster" {
  command = plan

  assert {
    condition     = length(data.azurerm_redis_enterprise_database.this) == 1
    error_message = "The cache resource exposes only a hostname, so the keys come from the database."
  }
}

run "keys_can_be_turned_off_for_entra_only_access" {
  command = plan

  variables {
    access_keys_enabled = false
  }

  assert {
    condition     = one(azurerm_managed_redis.this.default_database).access_keys_authentication_enabled == false
    error_message = "Turning keys off should reach the database configuration."
  }

  assert {
    condition     = length(data.azurerm_redis_enterprise_database.this) == 0
    error_message = "With keys off there is nothing to read."
  }
}

run "disabling_the_private_endpoint_reopens_public_access" {
  command = plan

  variables {
    enable_private_endpoint = false
  }

  assert {
    condition     = azurerm_managed_redis.this.public_network_access == "Enabled"
    error_message = "Without a private endpoint the cache has to be reachable somehow."
  }

  assert {
    condition     = length(azurerm_private_endpoint.this) == 0
    error_message = "No private endpoint should be created."
  }
}

run "an_existing_dns_zone_is_reused" {
  command = plan

  variables {
    private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/privateDnsZones/privatelink.redis.azure.net"
  }

  assert {
    condition     = length(azurerm_private_dns_zone.this) == 0
    error_message = "privatelink.redis.azure.net is a fixed name, so a second cache in the group must reuse the first one's zone."
  }
}

run "reusing_a_dns_zone_needs_no_virtual_network" {
  command = plan

  # The virtual network is only used to link a zone this module creates. A
  # caller who brings their own has already linked it.
  variables {
    virtual_network_id  = null
    private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/privateDnsZones/privatelink.redis.azure.net"
  }

  assert {
    condition     = length(azurerm_private_endpoint.this) == 1
    error_message = "The private endpoint should still be created."
  }

  assert {
    condition     = length(azurerm_private_dns_zone_virtual_network_link.this) == 0
    error_message = "There is no zone of our own to link."
  }
}

run "rejects_a_private_endpoint_with_no_dns_anywhere" {
  command = plan

  variables {
    virtual_network_id  = null
    private_dns_zone_id = null
  }

  expect_failures = [var.enable_private_endpoint]
}

run "rejects_a_sku_that_is_not_one" {
  command = plan

  variables {
    sku_name = "Standard_C3"
  }

  expect_failures = [var.sku_name]
}

run "rejects_a_family_spliced_to_the_wrong_letter" {
  command = plan

  # Each family has its own letter. Balanced uses B, so Balanced_C3 is two
  # families spliced together rather than a size.
  variables {
    sku_name = "Balanced_C3"
  }

  expect_failures = [var.sku_name]
}

run "accepts_each_family_with_its_own_letter" {
  command = plan

  variables {
    sku_name = "MemoryOptimized_M10"
  }

  assert {
    condition     = azurerm_managed_redis.this.sku_name == "MemoryOptimized_M10"
    error_message = "A correctly paired SKU should reach the resource."
  }
}

run "rejects_a_redis_style_eviction_policy" {
  command = plan

  # Redis Enterprise spells these differently: VolatileLRU, not volatile-lru.
  variables {
    eviction_policy = "volatile-lru"
  }

  expect_failures = [var.eviction_policy]
}

run "rejects_an_unknown_clustering_policy" {
  command = plan

  variables {
    clustering_policy = "Sharded"
  }

  expect_failures = [var.clustering_policy]
}

# A caller who has set a hash-tagged kombu `global_keyprefix` can use the sharded
# single-endpoint policy, so it stays selectable rather than being validated away.
run "accepts_the_enterprise_clustering_policy" {
  command = plan

  variables {
    clustering_policy = "EnterpriseCluster"
  }

  assert {
    condition     = one(azurerm_managed_redis.this.default_database).clustering_policy == "EnterpriseCluster"
    error_message = "EnterpriseCluster must stay selectable for callers that key-prefix around CROSSSLOT."
  }
}

run "rejects_a_cache_nothing_can_reach" {
  command = plan

  variables {
    enable_private_endpoint       = false
    public_network_access_enabled = false
  }

  expect_failures = [var.public_network_access_enabled]
}

run "rejects_a_critical_threshold_below_the_warning_one" {
  command = plan

  variables {
    memory_high_threshold_percent     = 90
    memory_critical_threshold_percent = 80
  }

  expect_failures = [var.memory_critical_threshold_percent]
}
