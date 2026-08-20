# Plans the module against mocked providers, so these run without an Azure
# subscription or a cluster. Run with `terraform test` from the module directory.

mock_provider "azurerm" {}
mock_provider "kubernetes" {}

variables {
  cluster_name        = "onyx-prod"
  resource_group_name = "onyx-rg"
  location            = "eastus"
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet/subnets/onyx-aks"

  # The module now refuses a public API server that no range restricts, so every
  # case below has to say what it wants. This is the ordinary answer.
  api_server_authorized_ip_ranges = ["203.0.113.0/24"]
}

run "defaults" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.this.oidc_issuer_enabled == true
    error_message = "Workload identity needs the OIDC issuer on."
  }

  assert {
    condition     = azurerm_kubernetes_cluster.this.workload_identity_enabled == true
    error_message = "Workload identity is how a pod reaches storage without a key."
  }

  assert {
    condition     = one(azurerm_kubernetes_cluster.this.default_node_pool).temporary_name_for_rotation == local.rotation_names["main"]
    error_message = "Without a rotation name, changing a system pool property replaces the whole cluster."
  }

  assert {
    condition     = one(azurerm_kubernetes_cluster.this.network_profile).outbound_type == "userAssignedNATGateway"
    error_message = "Egress should use the NAT gateway the vnet module puts on the subnet, so it keeps one address."
  }

  # network_policy is Optional+Computed, so a null reads as unknown until apply.
  # The plugin mode below is set outright, and the rejects_cilium_without_overlay
  # case covers the constraint that actually matters.
  assert {
    condition     = one(azurerm_kubernetes_cluster.this.network_profile).network_plugin_mode == "overlay"
    error_message = "Overlay keeps pod addresses out of the subnet, so the subnet only has to hold nodes."
  }
}

run "dns_service_ip_is_derived_from_the_service_range" {
  command = plan

  assert {
    condition     = one(azurerm_kubernetes_cluster.this.network_profile).dns_service_ip == "172.16.0.10"
    error_message = "The DNS service address should be taken from service_cidr so it cannot fall outside it."
  }
}

run "dns_service_ip_follows_a_changed_service_range" {
  command = plan

  variables {
    service_cidr = "10.240.0.0/16"
  }

  assert {
    condition     = one(azurerm_kubernetes_cluster.this.network_profile).dns_service_ip == "10.240.0.10"
    error_message = "Changing service_cidr must move the DNS service address with it."
  }
}

run "index_pool_runs_by_default" {
  command = plan

  assert {
    condition     = contains(keys(azurerm_kubernetes_cluster_node_pool.this), "index")
    error_message = "Azure has no managed OpenSearch, so the document index runs in the cluster by default."
  }

  assert {
    condition     = contains(azurerm_kubernetes_cluster_node_pool.this["index"].node_taints, "document-index=true:NoSchedule")
    error_message = "The index pool must be tainted so only the index lands on it."
  }
}

run "index_pool_can_be_turned_off" {
  command = plan

  variables {
    index_node_pool_enabled = false
  }

  assert {
    condition     = length(azurerm_kubernetes_cluster_node_pool.this) == 0
    error_message = "Turning the index pool off should leave only the system pool."
  }
}

run "optional_pools_are_tainted_and_labelled" {
  command = plan

  variables {
    enable_gpu_node_pool     = true
    enable_sandbox_node_pool = true
  }

  assert {
    condition     = length(azurerm_kubernetes_cluster_node_pool.this) == 3
    error_message = "index, gpu and sandbox should all be present."
  }

  assert {
    condition     = contains(azurerm_kubernetes_cluster_node_pool.this["gpu"].node_taints, "nvidia.com/gpu=true:NoSchedule")
    error_message = "Only pods that tolerate the GPU taint should land on the GPU pool."
  }

  assert {
    condition     = azurerm_kubernetes_cluster_node_pool.this["sandbox"].node_labels["onyx.app/workload"] == "sandbox"
    error_message = "Sandbox pods select their pool by label."
  }
}

run "no_storage_account_means_no_identity" {
  command = plan

  assert {
    condition     = length(azurerm_user_assigned_identity.workload) == 0
    error_message = "Nothing to grant means nothing to create, matching the AWS module."
  }

  assert {
    condition     = length(azurerm_federated_identity_credential.workload) == 0
    error_message = "No identity means no federated credentials."
  }

  assert {
    condition     = length(kubernetes_service_account.workload) == 0
    error_message = "No identity means no service account to annotate."
  }
}

run "a_storage_account_federates_the_service_account" {
  command = plan

  variables {
    storage_account_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxfilestore"]
  }

  assert {
    condition     = length(azurerm_federated_identity_credential.workload) == 1
    error_message = "One credential per service account."
  }

  assert {
    condition     = azurerm_federated_identity_credential.workload["onyx-workload-access"].subject == "system:serviceaccount:onyx:onyx-workload-access"
    error_message = "The subject is the same system:serviceaccount string the AWS module puts in an IRSA trust policy."
  }

  assert {
    condition     = azurerm_federated_identity_credential.workload["onyx-workload-access"].audience[0] == "api://AzureADTokenExchange"
    error_message = "Azure only exchanges tokens for this audience."
  }

  # Counted, not keyed by id: the ids normally arrive from a storage module in
  # the same apply and are unknown at plan time. The onyx composition's tests
  # are what exercise that case, since only there are the ids actually unknown.
  assert {
    condition     = azurerm_role_assignment.workload_storage[0].role_definition_name == "Storage Blob Data Contributor"
    error_message = "The identity should get blob data access on the account, and nothing wider."
  }

  assert {
    condition     = kubernetes_service_account.workload[0].metadata[0].labels["azure.workload.identity/use"] == "true"
    error_message = "Without this label the webhook never projects a token into the pod."
  }
}

run "every_supplied_storage_account_gets_a_role_assignment" {
  command = plan

  variables {
    storage_account_ids = [
      "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxfilestore",
      "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxuploads",
    ]
  }

  assert {
    condition     = length(azurerm_role_assignment.workload_storage) == 2
    error_message = "One role assignment per storage account."
  }

  assert {
    condition     = length(azurerm_federated_identity_credential.workload) == 1
    error_message = "More accounts does not mean more service accounts."
  }
}

run "the_namespace_is_created_before_the_service_account" {
  command = plan

  variables {
    storage_account_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxfilestore"]
  }

  assert {
    condition     = length(kubernetes_namespace.workload) == 1
    error_message = "On a fresh cluster nothing else has made the namespace, and the service account cannot exist without it."
  }

  assert {
    condition     = kubernetes_namespace.workload[0].metadata[0].name == "onyx"
    error_message = "The namespace created should be the one the service account lives in."
  }
}

run "the_namespace_can_be_left_to_something_else" {
  command = plan

  variables {
    storage_account_ids       = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxfilestore"]
    create_workload_namespace = false
  }

  assert {
    condition     = length(kubernetes_namespace.workload) == 0
    error_message = "A caller whose namespace already exists should not have a second one created."
  }

  assert {
    condition     = length(kubernetes_service_account.workload) == 1
    error_message = "The service account is still created either way."
  }
}

run "no_identity_means_no_namespace" {
  command = plan

  assert {
    condition     = length(kubernetes_namespace.workload) == 0
    error_message = "With no storage account there is no service account, so there is nothing to make a namespace for."
  }
}

run "additional_service_accounts_are_federated_but_not_created" {
  command = plan

  variables {
    storage_account_ids                       = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxfilestore"]
    additional_workload_service_account_names = ["onyx-sandbox-proxy"]
  }

  assert {
    condition     = length(azurerm_federated_identity_credential.workload) == 2
    error_message = "A chart-created service account still needs its own credential."
  }

  assert {
    condition     = length(kubernetes_service_account.workload) == 1
    error_message = "The module creates only its own service account; the chart owns the others."
  }
}

run "the_storage_class_is_not_default_unless_asked" {
  command = plan

  assert {
    condition     = length(kubernetes_storage_class.premium[0].metadata[0].annotations) == 0
    error_message = "AKS already ships a default class, so marking a second one would leave the cluster with two."
  }

  assert {
    condition     = kubernetes_storage_class.premium[0].volume_binding_mode == "WaitForFirstConsumer"
    error_message = "A managed disk is created in one zone, so binding has to wait for the scheduler."
  }
}

run "no_workspace_means_no_diagnostics" {
  command = plan

  assert {
    condition     = length(azurerm_monitor_diagnostic_setting.this) == 0
    error_message = "Control plane logs need somewhere to go."
  }
}

run "rotation_names_are_unique_and_valid_pool_names" {
  command = plan

  variables {
    enable_gpu_node_pool     = true
    enable_sandbox_node_pool = true
  }

  assert {
    condition = alltrue([
      for name in values(local.rotation_names) : can(regex("^[a-z][a-z0-9]{0,11}$", name))
    ])
    error_message = "A rotation name has to be a valid AKS pool name: at most 12 characters, starting with a lowercase letter."
  }

  assert {
    condition     = length(distinct(values(local.rotation_names))) == length(local.rotation_names)
    error_message = "Two pools sharing a rotation name would collide when either rotates."
  }
}

run "pools_sharing_a_prefix_still_get_distinct_rotation_names" {
  command = plan

  # Truncating the key alone would give both of these the same rotation name.
  variables {
    node_pools = {
      main    = { vm_size = "Standard_D8ds_v5" }
      workera = { vm_size = "Standard_D8ds_v5" }
      workerb = { vm_size = "Standard_D8ds_v5" }
    }
    index_node_pool_enabled = false
  }

  assert {
    condition     = length(distinct(values(local.rotation_names))) == 3
    error_message = "Pools whose names share their first six characters must still get distinct rotation names."
  }
}

run "the_role_assignment_survives_directory_replication_lag" {
  command = plan

  variables {
    storage_account_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxfilestore"]
  }

  assert {
    condition     = azurerm_role_assignment.workload_storage[0].skip_service_principal_aad_check == true
    error_message = "The identity is created in the same apply, so Entra may not have replicated it when the assignment is made."
  }
}

run "a_long_namespace_still_produces_a_valid_credential_name" {
  command = plan

  # Azure caps a federated credential name at 120 characters, and a namespace
  # and a service account name can each be 63.
  variables {
    storage_account_ids                = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Storage/storageAccounts/onyxfilestore"]
    workload_service_account_namespace = "onyx-production-workloads-with-a-deliberately-long-namespace-nm"
    workload_service_account_name       = "onyx-workload-access-with-a-deliberately-long-service-account-n"
  }

  assert {
    condition = alltrue([
      for n in values(local.federated_credential_names) : length(n) <= 120
    ])
    error_message = "A federated credential name must fit inside Azure's 120-character limit."
  }

  assert {
    condition     = length(distinct(values(local.federated_credential_names))) == length(local.federated_credential_names)
    error_message = "Truncated names must stay distinct."
  }
}

run "rejects_a_pool_named_after_another_pools_rotation_name" {
  command = plan

  # "mainb28b7a" is the rotation name generated for the "main" pool.
  variables {
    node_pools = {
      main       = { vm_size = "Standard_D8ds_v5" }
      mainb28b7a = { vm_size = "Standard_D8ds_v5" }
    }
    index_node_pool_enabled = false
  }

  expect_failures = [var.node_pools]
}

run "rejects_an_open_control_plane" {
  command = plan

  variables {
    api_server_authorized_ip_ranges = []
  }

  expect_failures = [var.allow_unrestricted_api_server_access]
}

run "an_open_control_plane_can_be_asked_for_explicitly" {
  command = plan

  variables {
    api_server_authorized_ip_ranges     = []
    allow_unrestricted_api_server_access = true
  }

  assert {
    condition     = length(azurerm_kubernetes_cluster.this.api_server_access_profile) == 0
    error_message = "With no ranges there is no access profile to write."
  }
}

run "a_private_cluster_needs_no_ranges" {
  command = plan

  variables {
    api_server_authorized_ip_ranges = []
    private_cluster_enabled         = true
  }

  assert {
    condition     = azurerm_kubernetes_cluster.this.private_cluster_enabled == true
    error_message = "A private API server is the other way to satisfy the rule."
  }
}

run "rejects_taints_on_the_system_pool" {
  command = plan

  # AKS accepts no taints on the system pool, and the provider has no argument
  # to pass them through, so silently dropping them would be worse.
  variables {
    node_pools = {
      main = {
        vm_size     = "Standard_D8ds_v5"
        node_taints = ["dedicated=onyx:NoSchedule"]
      }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_private_cluster_with_authorized_ranges" {
  command = plan

  variables {
    private_cluster_enabled        = true
    api_server_authorized_ip_ranges = ["203.0.113.0/24"]
  }

  expect_failures = [var.private_cluster_enabled]
}

run "rejects_cilium_without_overlay" {
  command = plan

  variables {
    network_policy      = "cilium"
    network_plugin_mode = null
  }

  expect_failures = [var.network_policy]
}

run "rejects_node_pools_without_a_system_pool" {
  command = plan

  variables {
    node_pools = {
      workers = {
        vm_size = "Standard_D8ds_v5"
      }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_pool_name_azure_would_reject" {
  command = plan

  variables {
    node_pools = {
      main               = { vm_size = "Standard_D8ds_v5" }
      document-index-pool = { vm_size = "Standard_E8ds_v5" }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_pool_whose_max_is_below_its_min" {
  command = plan

  variables {
    node_pools = {
      main = {
        vm_size   = "Standard_D8ds_v5"
        min_count = 5
        max_count = 2
      }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_azure_rbac_with_nobody_to_administer_it" {
  command = plan

  variables {
    entra_rbac_enabled = true
  }

  expect_failures = [var.entra_rbac_enabled]
}

run "rejects_an_unknown_log_category" {
  command = plan

  variables {
    log_analytics_workspace_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.OperationalInsights/workspaces/onyx-logs"
    control_plane_log_categories = ["kube-apiserver", "authenticator"]
  }

  expect_failures = [var.control_plane_log_categories]
}
