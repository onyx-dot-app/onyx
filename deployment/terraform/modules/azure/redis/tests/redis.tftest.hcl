# Plans the module against a mocked provider, so these run without an Azure
# subscription or credentials. Run with `terraform test` from the module directory.

mock_provider "azurerm" {}

variables {
  name                       = "onyx-redis-prod"
  resource_group_name        = "onyx-rg"
  location                   = "eastus"
  private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet/subnets/onyx-private-endpoints"
  virtual_network_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet"
}

run "defaults_are_private_and_tls_only" {
  command = plan

  assert {
    condition     = azurerm_redis_cache.this.non_ssl_port_enabled == false
    error_message = "The cache must not answer on the plaintext port."
  }

  assert {
    condition     = azurerm_redis_cache.this.minimum_tls_version == "1.2"
    error_message = "The cache should refuse TLS below 1.2."
  }

  assert {
    condition     = azurerm_redis_cache.this.public_network_access_enabled == false
    error_message = "A cache behind a private endpoint has no reason to answer on its public hostname."
  }

  assert {
    condition     = length(azurerm_private_endpoint.this) == 1
    error_message = "The private endpoint should be created by default."
  }

  assert {
    condition     = one(azurerm_private_endpoint.this[0].private_service_connection).subresource_names[0] == "redisCache"
    error_message = "The private endpoint must target the cache subresource."
  }
}

run "default_size_matches_the_aws_module" {
  command = plan

  assert {
    condition = alltrue([
      azurerm_redis_cache.this.sku_name == "Standard",
      azurerm_redis_cache.this.family == "C",
      azurerm_redis_cache.this.capacity == 3,
    ])
    error_message = "Standard C3 is 6 GB with a replica, the size the AWS module defaults to."
  }
}

run "four_alerts_exist_and_stay_silent" {
  command = plan

  assert {
    condition     = length(azurerm_monitor_metric_alert.memory_high.action) == 0
    error_message = "With no action group the alerts must exist but notify nothing."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.evicted_keys.criteria[0].metric_name == "evictedkeys"
    error_message = "Azure exposes no swap metric, so evictions replace the AWS swap alarm."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.evicted_keys.criteria[0].aggregation == "Total"
    error_message = "Evictions are a count over the window, not an average."
  }

  assert {
    condition     = azurerm_monitor_metric_alert.server_load.criteria[0].metric_name == "serverLoad"
    error_message = "Redis runs commands on one thread, so server load is the meaningful CPU signal."
  }
}

run "disabling_the_private_endpoint_reopens_public_access" {
  command = plan

  variables {
    enable_private_endpoint = false
  }

  assert {
    condition     = azurerm_redis_cache.this.public_network_access_enabled == true
    error_message = "Without a private endpoint the cache has to be reachable somehow."
  }

  assert {
    condition     = length(azurerm_private_endpoint.this) == 0
    error_message = "No private endpoint should be created."
  }

  assert {
    condition     = length(azurerm_private_dns_zone.this) == 0
    error_message = "The private DNS zone only exists to serve the private endpoint."
  }
}

run "an_existing_dns_zone_is_reused" {
  command = plan

  variables {
    private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/privateDnsZones/privatelink.redis.cache.windows.net"
  }

  assert {
    condition     = length(azurerm_private_dns_zone.this) == 0
    error_message = "privatelink.redis.cache.windows.net is a fixed name, so a second cache in the group must reuse the first one's zone."
  }
}

run "reusing_a_dns_zone_needs_no_virtual_network" {
  command = plan

  # The virtual network is only used to link a zone the module creates. A
  # caller who brings their own zone has already linked it.
  variables {
    virtual_network_id  = null
    private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/privateDnsZones/privatelink.redis.cache.windows.net"
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

run "rejects_a_critical_threshold_below_the_warning_one" {
  command = plan

  variables {
    memory_high_threshold_percent     = 90
    memory_critical_threshold_percent = 80
  }

  expect_failures = [var.memory_critical_threshold_percent]
}

run "rejects_a_fractional_capacity" {
  command = plan

  variables {
    capacity = 2.5
  }

  expect_failures = [var.capacity]
}

run "rejects_a_cache_nothing_can_reach" {
  command = plan

  # No private endpoint and no public hostname means every Redis-dependent
  # workload fails at runtime rather than at plan.
  variables {
    enable_private_endpoint       = false
    public_network_access_enabled = false
  }

  expect_failures = [var.public_network_access_enabled]
}

run "rejects_a_family_that_does_not_match_the_tier" {
  command = plan

  variables {
    sku_name = "Premium"
    family   = "C"
  }

  expect_failures = [var.family]
}

run "rejects_a_capacity_outside_the_family" {
  command = plan

  variables {
    sku_name = "Premium"
    family   = "P"
    capacity = 6
  }

  expect_failures = [var.capacity]
}

run "rejects_zones_on_a_tier_that_cannot_use_them" {
  command = plan

  variables {
    zones = ["1", "2"]
  }

  expect_failures = [var.zones]
}

run "rejects_turning_off_every_way_in" {
  command = plan

  variables {
    access_keys_enabled = false
  }

  expect_failures = [var.access_keys_enabled]
}

run "rejects_a_private_endpoint_with_nowhere_to_put_it" {
  command = plan

  variables {
    private_endpoint_subnet_id = null
  }

  expect_failures = [var.enable_private_endpoint]
}

run "rejects_an_unknown_eviction_policy" {
  command = plan

  variables {
    maxmemory_policy = "evict-everything"
  }

  expect_failures = [var.maxmemory_policy]
}
