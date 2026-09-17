locals {
  workspace   = terraform.workspace
  merged_tags = merge(var.tags, { tenant = var.name, environment = local.workspace })

  resource_group_name_desired = coalesce(var.resource_group_name, "${var.name}-${local.workspace}")

  cluster_name  = "${var.name}-${local.workspace}"
  postgres_name = "${var.name}-postgres-${local.workspace}"
  redis_name    = "${var.name}-redis-${local.workspace}"

  # Storage account names are globally unique and allow only 24 lowercase
  # alphanumeric characters, so the readable prefix is truncated and a short
  # digest of the full identity is appended to keep collisions unlikely.
  storage_name_digest    = substr(sha1("${var.name}-${local.workspace}-${var.location}-${local.resource_group_name_desired}"), 0, 6)
  storage_name_sanitized = replace(lower("${var.name}${local.workspace}files"), "/[^a-z0-9]/", "")
  storage_name_prefix    = substr(local.storage_name_sanitized, 0, 18)
  storage_account_name = coalesce(
    var.storage_account_name,
    "${local.storage_name_prefix}${local.storage_name_digest}",
  )
  # 15 + len("log") + 6 = 24, so the digest survives in full here too.
  flow_log_storage_account_name = "${substr(local.storage_name_sanitized, 0, 15)}log${local.storage_name_digest}"

  virtual_network_id         = var.create_virtual_network ? module.vnet[0].vnet_id : var.virtual_network_id
  aks_subnet_id              = var.create_virtual_network ? module.vnet[0].aks_subnet_id : var.aks_subnet_id
  postgres_subnet_id         = var.create_virtual_network ? module.vnet[0].postgres_subnet_id : var.postgres_subnet_id
  private_endpoint_subnet_id = var.create_virtual_network ? module.vnet[0].private_endpoint_subnet_id : var.private_endpoint_subnet_id

  # A supplied subnet may already carry a NAT gateway, which only the caller
  # knows about, so the derived value is a default rather than a decision.
  aks_outbound_type = coalesce(
    var.aks_outbound_type,
    var.create_virtual_network && var.enable_nat_gateway ? "userAssignedNATGateway" : "loadBalancer",
  )

  nat_gateway_ips   = var.create_virtual_network ? module.vnet[0].nat_gateway_public_ips : []
  trusted_nat_ips   = var.waf_trust_nat_gateway_ip ? local.nat_gateway_ips : []
  nat_gateway_cidrs = [for ip in local.nat_gateway_ips : "${ip}/32"]

  # A cluster whose API server allowlist excludes the cluster's own egress is
  # broken, not locked down. With outbound_type = userAssignedNATGateway, AKS
  # does not add the egress address for you the way it does when it manages
  # outbound, so anything in the cluster that reaches the API server through the
  # public endpoint is refused: node bootstrap, and every in-cluster client that
  # uses its service account.
  #
  # Empty stays empty. An empty list means "no restriction", and adding an
  # address to it would silently turn that into a restriction.
  api_server_authorized_ip_ranges = length(var.api_server_authorized_ip_ranges) == 0 ? [] : distinct(concat(
    var.api_server_authorized_ip_ranges,
    var.trust_nat_gateway_ip_on_api_server ? local.nat_gateway_cidrs : [],
  ))

  waf_allowed_ip_cidrs           = distinct(concat(var.waf_allowed_ip_cidrs, local.trusted_nat_ips))
  waf_rate_limit_exempt_ip_cidrs = distinct(concat(var.waf_rate_limit_exempt_ip_cidrs, local.trusted_nat_ips))

  # T-shirt size defaults, chosen so each tier lands on the Azure size closest
  # to what the AWS composition picks. The index pool is memory-optimised
  # because on Azure it carries the document index itself: there is no managed
  # OpenSearch to move that load off the cluster.
  size_defaults = {
    small = {
      main_node_vm_size       = "Standard_D8ds_v5"
      main_node_min_count     = 1
      main_node_max_count     = 3
      index_node_vm_size      = "Standard_E4ds_v5"
      index_node_disk_size_gb = 256
      postgres_sku_name       = "GP_Standard_D2ds_v5"
      postgres_storage_gb     = 64
      redis_sku_name          = "Balanced_B5"
    }
    medium = {
      main_node_vm_size       = "Standard_D16ds_v5"
      main_node_min_count     = 1
      main_node_max_count     = 5
      index_node_vm_size      = "Standard_E8ds_v5"
      index_node_disk_size_gb = 512
      postgres_sku_name       = "GP_Standard_D2ds_v5"
      postgres_storage_gb     = 128
      redis_sku_name          = "Balanced_B10"
    }
    large = {
      main_node_vm_size       = "Standard_D16ds_v5"
      main_node_min_count     = 2
      main_node_max_count     = 8
      index_node_vm_size      = "Standard_E16ds_v5"
      index_node_disk_size_gb = 1024
      postgres_sku_name       = "GP_Standard_D4ds_v5"
      postgres_storage_gb     = 256
      redis_sku_name          = "Balanced_B20"
    }
  }
  sizing = local.size_defaults[var.size]

  # An explicitly set variable always wins over its tier default.
  main_node_vm_size       = coalesce(var.main_node_vm_size, local.sizing.main_node_vm_size)
  main_node_min_count     = coalesce(var.main_node_min_count, local.sizing.main_node_min_count)
  main_node_max_count     = coalesce(var.main_node_max_count, local.sizing.main_node_max_count)
  index_node_vm_size      = coalesce(var.index_node_vm_size, local.sizing.index_node_vm_size)
  index_node_disk_size_gb = coalesce(var.index_node_disk_size_gb, local.sizing.index_node_disk_size_gb)
  postgres_sku_name       = coalesce(var.postgres_sku_name, local.sizing.postgres_sku_name)
  postgres_storage_gb     = coalesce(var.postgres_storage_gb, local.sizing.postgres_storage_gb)
  redis_sku_name          = coalesce(var.redis_sku_name, local.sizing.redis_sku_name)

  node_pools = merge(
    {
      main = {
        vm_size   = local.main_node_vm_size
        min_count = local.main_node_min_count
        max_count = local.main_node_max_count
      }
    },
    var.index_node_pool_enabled ? {
      index = {
        vm_size         = local.index_node_vm_size
        min_count       = 1
        max_count       = 1
        os_disk_size_gb = local.index_node_disk_size_gb
        node_labels     = { "onyx.app/workload" = "document-index" }
        node_taints     = ["document-index=true:NoSchedule"]
      }
    } : {},
  )
}

resource "azurerm_resource_group" "this" {
  count = var.create_resource_group ? 1 : 0

  name     = local.resource_group_name_desired
  location = var.location
  tags     = local.merged_tags
}

locals {
  # Reading the name back off the resource is what orders every module after
  # the group, without each one needing its own depends_on.
  resource_group_name = var.create_resource_group ? azurerm_resource_group.this[0].name : local.resource_group_name_desired
}

module "vnet" {
  source = "../vnet"
  count  = var.create_virtual_network ? 1 : 0

  name                = var.name
  resource_group_name = local.resource_group_name
  location            = var.location
  address_space       = var.address_space
  enable_nat_gateway  = var.enable_nat_gateway
  tags                = local.merged_tags

  enable_flow_logs                    = var.enable_flow_logs
  flow_log_storage_account_id         = var.enable_flow_logs ? module.storage_flow_logs[0].storage_account_id : null
  network_watcher_name                = coalesce(var.network_watcher_name, "NetworkWatcher_${var.location}")
  network_watcher_resource_group_name = var.network_watcher_resource_group_name
}

# A separate account for flow logs. It takes no subnets, which is what keeps
# the dependency one-way: this account, then the network, then the file store
# account that restricts itself to the network's subnets.
module "storage_flow_logs" {
  source = "../storage"
  count  = var.enable_flow_logs ? 1 : 0

  storage_account_name = local.flow_log_storage_account_name
  container_name       = "flow-logs"
  resource_group_name  = local.resource_group_name
  location             = var.location
  tags                 = local.merged_tags

  account_replication_type = "LRS"
  enable_versioning        = false
  transition_to_cool       = false
}

module "storage" {
  source = "../storage"

  storage_account_name = local.storage_account_name
  container_name       = var.storage_container_name
  resource_group_name  = local.resource_group_name
  location             = var.location
  tags                 = local.merged_tags

  account_replication_type = var.storage_account_replication_type
  allowed_subnet_ids       = var.restrict_storage_to_cluster ? [local.aks_subnet_id] : []
}

module "postgres" {
  source = "../postgres"

  name                = local.postgres_name
  resource_group_name = local.resource_group_name
  location            = var.location
  tags                = local.merged_tags

  db_name        = var.postgres_db_name
  engine_version = var.postgres_engine_version
  sku_name       = local.postgres_sku_name
  storage_gb     = local.postgres_storage_gb

  delegated_subnet_id = local.postgres_subnet_id
  virtual_network_id  = local.virtual_network_id

  username = var.postgres_username
  password = var.postgres_password

  enable_entra_authentication        = var.enable_entra_database_authentication
  entra_authentication_only          = var.entra_database_authentication_only
  entra_administrator_object_id      = var.database_administrator_object_id
  entra_administrator_principal_name = var.database_administrator_principal_name
  entra_administrator_principal_type = var.database_administrator_principal_type
  tenant_id                          = var.tenant_id

  high_availability_enabled = var.postgres_high_availability_enabled
  backup_retention_days     = var.postgres_backup_retention_days

  action_group_ids = var.action_group_ids
}

module "redis" {
  source = "../redis"
  count  = var.enable_redis ? 1 : 0

  name                = local.redis_name
  resource_group_name = local.resource_group_name
  location            = var.location
  tags                = local.merged_tags

  sku_name                  = local.redis_sku_name
  high_availability_enabled = var.redis_high_availability_enabled

  private_endpoint_subnet_id = local.private_endpoint_subnet_id
  virtual_network_id         = local.virtual_network_id

  action_group_ids = var.action_group_ids
}

module "aks" {
  source = "../aks"

  cluster_name        = local.cluster_name
  resource_group_name = local.resource_group_name
  location            = var.location
  kubernetes_version  = var.kubernetes_version
  subnet_id           = local.aks_subnet_id
  tags                = local.merged_tags

  node_pools              = local.node_pools
  index_node_pool_enabled = var.index_node_pool_enabled

  enable_gpu_node_pool     = var.enable_gpu_node_pool
  enable_sandbox_node_pool = var.enable_sandbox_node_pool

  private_cluster_enabled              = var.private_cluster_enabled
  api_server_authorized_ip_ranges      = local.api_server_authorized_ip_ranges
  allow_unrestricted_api_server_access = var.allow_unrestricted_api_server_access
  network_policy                       = var.network_policy

  # The vnet module puts a NAT gateway on the node subnet, so the cluster keeps
  # one egress address. Without that gateway AKS has to manage outbound itself.
  outbound_type = local.aks_outbound_type

  storage_account_ids                       = [module.storage.storage_account_id]
  additional_workload_service_account_names = var.additional_workload_service_account_names
  create_workload_service_account           = var.create_workload_service_account
  create_workload_namespace                 = var.create_workload_namespace

  log_analytics_workspace_id        = var.log_analytics_workspace_id
  entra_rbac_admin_group_object_ids = var.entra_rbac_admin_group_object_ids
}

module "waf" {
  source = "../waf"
  count  = var.enable_waf ? 1 : 0

  name                = var.name
  resource_group_name = local.resource_group_name
  location            = var.location
  tags                = local.merged_tags

  mode                                  = var.waf_mode
  allowed_ip_cidrs                      = local.waf_allowed_ip_cidrs
  rate_limit_exempt_ip_cidrs            = local.waf_rate_limit_exempt_ip_cidrs
  geo_restriction_countries             = var.waf_geo_restriction_countries
  rate_limit_requests_per_5_minutes     = var.waf_rate_limit_requests_per_5_minutes
  api_rate_limit_requests_per_5_minutes = var.waf_api_rate_limit_requests_per_5_minutes
}
