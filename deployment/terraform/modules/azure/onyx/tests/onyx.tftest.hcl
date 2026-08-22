# Plans the whole composition against mocked providers, so these run without an
# Azure subscription. Run with `terraform test` from the module directory.

mock_provider "azurerm" {}
mock_provider "kubernetes" {}

variables {
  name              = "onyx"
  location          = "eastus"
  postgres_password = "not-a-real-password"

  # The composition now refuses a public API server that no range restricts, so
  # every case below has to say what it wants.
  api_server_authorized_ip_ranges = ["203.0.113.0/24"]
}

run "medium_is_the_default_tier" {
  command = plan

  assert {
    condition     = local.main_node_vm_size == "Standard_D16ds_v5"
    error_message = "Medium should land on the Azure size closest to the AWS composition's m7i.4xlarge."
  }

  assert {
    condition     = local.postgres_sku_name == "GP_Standard_D2ds_v5"
    error_message = "Medium keeps the small database SKU, matching the AWS composition."
  }

  assert {
    condition     = local.redis_sku_name == "Balanced_B10"
    error_message = "Balanced_B10 is about 10 GB, the closest Managed Redis shape to the AWS composition's cache.m6g.xlarge."
  }

  assert {
    condition     = local.index_node_vm_size == "Standard_E8ds_v5"
    error_message = "The index pool is memory-optimised because on Azure it carries the document index itself."
  }
}

run "small_and_large_move_every_knob_together" {
  command = plan

  variables {
    size = "small"
  }

  assert {
    condition = alltrue([
      local.main_node_vm_size == "Standard_D8ds_v5",
      local.main_node_max_count == 3,
      local.postgres_storage_gb == 64,
      local.index_node_disk_size_gb == 256,
    ])
    error_message = "The small tier should move compute, database and index sizing together."
  }
}

run "large_scales_the_index_pool_hardest" {
  command = plan

  variables {
    size = "large"
  }

  assert {
    condition     = local.index_node_vm_size == "Standard_E16ds_v5"
    error_message = "Large has no managed search service to offload to, so the index pool takes the load."
  }

  assert {
    condition     = local.index_node_disk_size_gb == 1024
    error_message = "The index needs room to grow on disk."
  }

  assert {
    condition     = local.postgres_sku_name == "GP_Standard_D4ds_v5"
    error_message = "Large moves the database off the smallest general purpose SKU."
  }
}

run "an_explicit_value_beats_its_tier_default" {
  command = plan

  variables {
    size                = "small"
    postgres_storage_gb = 512
    main_node_max_count = 10
  }

  assert {
    condition     = local.postgres_storage_gb == 512
    error_message = "An explicitly set variable must win over the tier default."
  }

  assert {
    condition     = local.main_node_max_count == 10
    error_message = "An explicitly set variable must win over the tier default."
  }

  assert {
    condition     = local.main_node_vm_size == "Standard_D8ds_v5"
    error_message = "Overriding one knob must not disturb the others in the tier."
  }
}

run "the_derived_storage_account_name_is_one_azure_accepts" {
  command = plan

  assert {
    condition     = can(regex("^[a-z0-9]{3,24}$", local.storage_account_name))
    error_message = "Storage account names allow only 3-24 lowercase alphanumeric characters."
  }

  assert {
    condition     = can(regex("^[a-z0-9]{3,24}$", local.flow_log_storage_account_name))
    error_message = "The flow log account name has to satisfy the same rule."
  }

  assert {
    condition     = local.storage_account_name != local.flow_log_storage_account_name
    error_message = "The two accounts must not collide on a name."
  }
}

run "both_account_names_keep_the_whole_digest" {
  command = plan

  # The flow log name also carries "log", so its prefix has to be shorter or
  # truncation eats the digest and two deployments can collide in Azure's
  # global namespace.
  variables {
    name = "onyx-enterprise-production-deployment"
  }

  assert {
    condition     = endswith(local.storage_account_name, local.storage_name_digest)
    error_message = "The file store account name must keep its whole digest."
  }

  assert {
    condition     = endswith(local.flow_log_storage_account_name, local.storage_name_digest)
    error_message = "The flow log account name must keep its whole digest too."
  }

  assert {
    condition     = length(local.flow_log_storage_account_name) <= 24
    error_message = "Storage account names allow at most 24 characters."
  }
}

run "a_long_name_still_produces_an_acceptable_account_name" {
  command = plan

  variables {
    name = "onyx-enterprise-production-deployment"
  }

  assert {
    condition     = can(regex("^[a-z0-9]{3,24}$", local.storage_account_name))
    error_message = "A long prefix must be truncated rather than producing a name Azure rejects."
  }
}

run "an_explicit_storage_account_name_is_used_as_given" {
  command = plan

  variables {
    storage_account_name = "onyxfilesprod"
  }

  assert {
    condition     = local.storage_account_name == "onyxfilesprod"
    error_message = "A supplied name should be used unchanged."
  }
}

run "the_resource_group_is_created_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_resource_group.this) == 1
    error_message = "The composition creates its own resource group by default."
  }

  assert {
    condition     = local.resource_group_name_desired == "onyx-default"
    error_message = "The group is named after the module name and the workspace."
  }
}

run "an_existing_resource_group_can_be_joined" {
  command = plan

  variables {
    create_resource_group = false
    resource_group_name   = "shared-rg"
  }

  assert {
    condition     = length(azurerm_resource_group.this) == 0
    error_message = "Joining an existing group must not create one."
  }

  assert {
    condition     = local.resource_group_name == "shared-rg"
    error_message = "The supplied group name should be used."
  }
}

run "flow_logs_bring_their_own_storage_account" {
  command = plan

  variables {
    enable_flow_logs = true
  }

  assert {
    condition     = length(module.storage_flow_logs) == 1
    error_message = "Flow logs need an account of their own, so the network never depends on the file store account."
  }
}

run "flow_logs_are_off_by_default" {
  command = plan

  assert {
    condition     = length(module.storage_flow_logs) == 0
    error_message = "Flow logs need a Network Watcher in the region, so they are opt-in."
  }
}

run "the_waf_exists_by_default" {
  command = plan

  assert {
    condition     = length(module.waf) == 1
    error_message = "The WAF policy is created by default so there is something to attach at the edge."
  }
}

run "egress_uses_the_nat_gateway_this_module_created" {
  command = plan

  assert {
    condition     = local.aks_outbound_type == "userAssignedNATGateway"
    error_message = "With a created network and a NAT gateway the cluster should keep one egress address."
  }
}

run "a_supplied_network_falls_back_to_load_balancer_egress" {
  command = plan

  variables {
    create_virtual_network     = false
    virtual_network_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing"
    aks_subnet_id              = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/aks"
    postgres_subnet_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/postgres"
    private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/pe"
  }

  assert {
    condition     = local.aks_outbound_type == "loadBalancer"
    error_message = "Without a NAT gateway of our own, AKS has to manage outbound."
  }
}

run "a_supplied_subnet_with_its_own_nat_gateway_can_say_so" {
  command = plan

  variables {
    create_virtual_network     = false
    virtual_network_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing"
    aks_subnet_id              = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/aks"
    postgres_subnet_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/postgres"
    private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/pe"
    aks_outbound_type          = "userAssignedNATGateway"
  }

  assert {
    condition     = local.aks_outbound_type == "userAssignedNATGateway"
    error_message = "A caller whose subnet already has a NAT gateway should keep its stable address."
  }
}

run "entra_only_needs_no_password" {
  command = plan

  variables {
    postgres_password                     = null
    enable_entra_database_authentication  = true
    entra_database_authentication_only    = true
    tenant_id                             = "00000000-0000-0000-0000-000000000000"
    database_administrator_object_id      = "11111111-1111-1111-1111-111111111111"
    database_administrator_principal_name = "onyx-db-admins"
  }

  assert {
    condition     = local.postgres_sku_name != null
    error_message = "The plan should succeed with no password at all, which is the point of this run."
  }
}

run "rejects_a_deployment_with_no_database_password" {
  command = plan

  variables {
    postgres_password = null
  }

  expect_failures = [var.postgres_password]
}

run "an_empty_api_allowlist_stays_empty" {
  command = plan

  # Empty means no restriction. Appending the egress address to it would
  # silently turn "open" into "only the cluster itself", which locks the
  # operator out of their own API server.
  variables {
    api_server_authorized_ip_ranges      = []
    allow_unrestricted_api_server_access = true
  }

  assert {
    condition     = length(local.api_server_authorized_ip_ranges) == 0
    error_message = "An empty allowlist must stay empty rather than becoming a one-entry allowlist."
  }
}

run "the_cluster_trusts_its_own_egress_by_default" {
  command = plan

  assert {
    condition     = var.trust_nat_gateway_ip_on_api_server
    error_message = "A cluster whose API allowlist excludes its own egress cannot bootstrap its nodes, so this defaults on."
  }

  # That the caller's own range survives the concat is not checkable here: the
  # egress address is unknown until apply, which makes the whole list unknown.
  # The empty-stays-empty case above is the one a mocked plan can see.
}

run "rejects_an_open_control_plane" {
  command = plan

  variables {
    api_server_authorized_ip_ranges = []
  }

  expect_failures = [var.allow_unrestricted_api_server_access]
}

run "rejects_flow_logs_on_a_network_it_does_not_manage" {
  command = plan

  # Otherwise the log storage account is created and nothing ever writes to it.
  variables {
    enable_flow_logs           = true
    create_virtual_network     = false
    virtual_network_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing"
    aks_subnet_id              = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/aks"
    postgres_subnet_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/postgres"
    private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/pe"
  }

  expect_failures = [var.enable_flow_logs]
}

run "bringing_your_own_network_needs_every_subnet" {
  command = plan

  variables {
    create_virtual_network = false
    virtual_network_id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/existing"
  }

  expect_failures = [var.create_virtual_network]
}

run "rejects_a_size_that_is_not_a_tier" {
  command = plan

  variables {
    size = "extra-large"
  }

  expect_failures = [var.size]
}

run "no_managed_redis_by_default" {
  command = plan

  # Managed Redis cannot serve Celery: it is always clustered, and the pidbox
  # opens a MULTI across hash slots. Provisioning one by default would bill for
  # a cache that Onyx cannot talk to.
  assert {
    condition     = length(module.redis) == 0
    error_message = "Managed Redis should be off unless asked for, because Onyx cannot use it."
  }

  assert {
    condition     = output.redis_host == null
    error_message = "With no cache there is no hostname to publish."
  }
}

run "managed_redis_can_still_be_asked_for" {
  command = plan

  variables {
    enable_redis = true
  }

  assert {
    condition     = length(module.redis) == 1
    error_message = "enable_redis should still create the cache for anyone who wants one."
  }
}
