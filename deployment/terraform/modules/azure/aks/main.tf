locals {
  # AKS requires the system pool inline on the cluster, so "main" is handled
  # separately from every other pool.
  main_pool = var.node_pools["main"]

  gpu_node_pool = var.enable_gpu_node_pool ? {
    gpu = {
      vm_size         = var.gpu_node_vm_size
      min_count       = 1
      max_count       = 1
      os_disk_size_gb = 100
      os_disk_type    = "Managed"
      node_labels     = { "onyx.app/gpu" = "true" }
      node_taints     = ["nvidia.com/gpu=true:NoSchedule"]
      zones           = []
      mode            = "User"
    }
  } : {}

  sandbox_node_pool = var.enable_sandbox_node_pool ? {
    sandbox = {
      vm_size         = var.sandbox_node_vm_size
      min_count       = var.sandbox_node_min_count
      max_count       = var.sandbox_node_max_count
      os_disk_size_gb = var.sandbox_node_disk_size_gb
      os_disk_type    = "Managed"
      node_labels     = { "onyx.app/workload" = "sandbox" }
      node_taints     = ["workload=sandbox:NoSchedule"]
      zones           = []
      mode            = "User"
    }
  } : {}

  additional_node_pools = merge(
    {
      for key, pool in var.node_pools : key => pool
      if key != "main" && (key != "index" || var.index_node_pool_enabled)
    },
    local.gpu_node_pool,
    local.sandbox_node_pool,
  )

  # Setting the DNS service address from the service range removes the chance
  # of picking one outside it, which AKS rejects.
  dns_service_ip = var.dns_service_ip != null ? var.dns_service_ip : cidrhost(var.service_cidr, 10)

  # AKS rotates a pool through a spare name when a property changes. The name
  # must be a valid pool name and unique across the cluster, so truncating the
  # key is not enough: two keys sharing six characters would collide. A digest
  # of the full key makes it unique.
  rotation_names = {
    for key in concat(["main"], keys(local.additional_node_pools)) :
    key => substr("${substr(key, 0, 6)}${substr(sha1(key), 0, 6)}", 0, 12)
  }

  workload_identity_enabled = length(var.storage_account_ids) > 0

  workload_service_account_names = distinct(concat(
    [var.workload_service_account_name],
    var.additional_workload_service_account_names,
  ))

  workload_service_account_subjects = {
    for name in local.workload_service_account_names :
    name => "system:serviceaccount:${var.workload_service_account_namespace}:${name}"
  }

  # Azure caps a federated credential name at 120 characters, and a namespace
  # and a service account name can each be 63. Truncating alone would let two
  # long names collide, so a digest of the full subject goes on the end.
  federated_credential_names = {
    for name, subject in local.workload_service_account_subjects :
    name => "${substr("${var.workload_service_account_namespace}-${name}", 0, 100)}-${substr(sha1(subject), 0, 8)}"
  }
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = var.cluster_name
  resource_group_name = var.resource_group_name
  location            = var.location
  dns_prefix          = var.cluster_name
  kubernetes_version  = var.kubernetes_version
  sku_tier            = var.sku_tier

  private_cluster_enabled           = var.private_cluster_enabled
  azure_policy_enabled              = var.azure_policy_enabled
  role_based_access_control_enabled = true

  # The pair that makes workload identity work. The issuer is the trust anchor
  # the federated credentials below point at.
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # This pool is always the system pool, so it takes no mode argument.
  default_node_pool {
    name    = "main"
    vm_size = local.main_pool.vm_size

    auto_scaling_enabled = true
    min_count            = local.main_pool.min_count
    max_count            = local.main_pool.max_count

    os_disk_size_gb = local.main_pool.os_disk_size_gb
    os_disk_type    = local.main_pool.os_disk_type
    node_labels     = local.main_pool.node_labels
    zones           = local.main_pool.zones
    vnet_subnet_id  = var.subnet_id

    # Without a name to rotate through, changing a property of the system pool
    # replaces the whole cluster instead of the pool.
    temporary_name_for_rotation = local.rotation_names["main"]

    # Azure sets this itself, so leaving it unmanaged shows as drift on every
    # plan and a stray apply would silently change how upgrades behave.
    upgrade_settings {
      max_surge = var.node_pool_max_surge
    }

    tags = var.tags
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = var.network_plugin_mode
    network_policy      = var.network_policy
    network_data_plane  = var.network_policy == "cilium" ? "cilium" : null
    pod_cidr            = var.network_plugin_mode == "overlay" ? var.pod_cidr : null
    service_cidr        = var.service_cidr
    dns_service_ip      = local.dns_service_ip
    outbound_type       = var.outbound_type
    load_balancer_sku   = "standard"
  }

  storage_profile {
    disk_driver_enabled         = true
    file_driver_enabled         = true
    blob_driver_enabled         = false
    snapshot_controller_enabled = true
  }

  dynamic "api_server_access_profile" {
    for_each = length(var.api_server_authorized_ip_ranges) > 0 ? [1] : []
    content {
      authorized_ip_ranges = var.api_server_authorized_ip_ranges
    }
  }

  dynamic "azure_active_directory_role_based_access_control" {
    for_each = length(var.entra_rbac_admin_group_object_ids) > 0 ? [1] : []
    content {
      admin_group_object_ids = var.entra_rbac_admin_group_object_ids
      azure_rbac_enabled     = var.entra_rbac_enabled
    }
  }

  dynamic "oms_agent" {
    for_each = var.log_analytics_workspace_id != null ? [1] : []
    content {
      log_analytics_workspace_id      = var.log_analytics_workspace_id
      msi_auth_for_monitoring_enabled = true
    }
  }

  tags = var.tags

  lifecycle {
    # AKS reports the node count the autoscaler settled on. Treating that as
    # drift would fight the autoscaler on every apply.
    ignore_changes = [default_node_pool[0].node_count]
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "this" {
  for_each = local.additional_node_pools

  name                  = each.key
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = each.value.vm_size
  mode                  = each.value.mode

  auto_scaling_enabled = true
  min_count            = each.value.min_count
  max_count            = each.value.max_count

  os_disk_size_gb = each.value.os_disk_size_gb
  os_disk_type    = each.value.os_disk_type
  node_labels     = each.value.node_labels
  node_taints     = each.value.node_taints
  zones           = each.value.zones
  vnet_subnet_id  = var.subnet_id

  temporary_name_for_rotation = local.rotation_names[each.key]

  # Managed for the same reason as the system pool's: Azure sets a default and
  # an unmanaged block reads as drift on every plan.
  upgrade_settings {
    max_surge = var.node_pool_max_surge
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [node_count]
  }
}

# --- Workload identity -------------------------------------------------------

resource "azurerm_user_assigned_identity" "workload" {
  count = local.workload_identity_enabled ? 1 : 0

  name                = "${var.cluster_name}-workload"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

# One credential per service account. The subject is the same
# system:serviceaccount:<namespace>:<name> string the AWS module puts in an
# IRSA trust policy; Azure matches it against the cluster's OIDC issuer.
resource "azurerm_federated_identity_credential" "workload" {
  for_each = local.workload_identity_enabled ? local.workload_service_account_subjects : {}

  name                      = local.federated_credential_names[each.key]
  user_assigned_identity_id = azurerm_user_assigned_identity.workload[0].id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject                   = each.value
}

# Counted rather than keyed by account id. The ids normally come from a storage
# module in the same apply, so they are not known at plan time, and a for_each
# over unknown keys fails the plan outright.
resource "azurerm_role_assignment" "workload_storage" {
  count = local.workload_identity_enabled ? length(var.storage_account_ids) : 0

  scope                = var.storage_account_ids[count.index]
  role_definition_name = var.storage_role_definition_name
  principal_id         = azurerm_user_assigned_identity.workload[0].principal_id
  principal_type       = "ServicePrincipal"

  # The identity is created in this same apply, and Entra does not always have
  # the service principal replicated by the time the assignment is made. Without
  # this the apply fails with a transient PrincipalNotFound.
  skip_service_principal_aad_check = true
}

# Created before the service account below, which cannot exist without it. The
# documented Helm install then targets this namespace rather than making its own.
resource "kubernetes_namespace" "workload" {
  count = local.workload_identity_enabled && var.create_workload_service_account && var.create_workload_namespace ? 1 : 0

  metadata {
    name = var.workload_service_account_namespace
  }

  depends_on = [azurerm_kubernetes_cluster.this]
}

resource "kubernetes_service_account" "workload" {
  count = local.workload_identity_enabled && var.create_workload_service_account ? 1 : 0

  depends_on = [azurerm_kubernetes_cluster.this]

  metadata {
    name = var.workload_service_account_name
    # Reading the name back off the namespace is what orders this after it.
    namespace = var.create_workload_namespace ? kubernetes_namespace.workload[0].metadata[0].name : var.workload_service_account_namespace

    annotations = {
      "azure.workload.identity/client-id" = azurerm_user_assigned_identity.workload[0].client_id
    }

    # Without this label the webhook does not project a token into the pod, and
    # the identity is never used.
    labels = {
      "azure.workload.identity/use" = "true"
    }
  }
}

# --- Cluster add-ons ---------------------------------------------------------

resource "kubernetes_storage_class" "premium" {
  count = var.create_premium_storage_class ? 1 : 0

  metadata {
    name = var.premium_storage_class_name
    annotations = var.premium_storage_class_is_default ? {
      "storageclass.kubernetes.io/is-default-class" = "true"
    } : {}
  }

  storage_provisioner = "disk.csi.azure.com"
  reclaim_policy      = "Delete"
  # A disk is created in one zone, so binding has to wait until the scheduler
  # has picked the node that will use it.
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    skuName = "Premium_LRS"
  }

  depends_on = [azurerm_kubernetes_cluster.this]
}

resource "azurerm_monitor_diagnostic_setting" "this" {
  count = var.log_analytics_workspace_id != null ? 1 : 0

  name                       = "${var.cluster_name}-diagnostics"
  target_resource_id         = azurerm_kubernetes_cluster.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  dynamic "enabled_log" {
    for_each = var.control_plane_log_categories
    content {
      category = enabled_log.value
    }
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
