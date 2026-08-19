variable "name" {
  type        = string
  description = "Name prefix for every resource. Example: \"onyx\"."
  default     = "onyx"
}

variable "location" {
  type        = string
  description = "Azure region for all resources, for example \"eastus\""
}

variable "create_resource_group" {
  type        = bool
  description = "Create the resource group. False joins one that already exists."
  default     = true
}

variable "resource_group_name" {
  type        = string
  description = "Resource group to create or join. Null names it \"<name>-<workspace>\"."
  default     = null
}

variable "tags" {
  type        = map(string)
  description = "Base tags applied to every resource"
  # Add an owner tag here if your asset inventory expects one. Everything set
  # here is stamped on every resource this module creates.
  default = {
    "project" = "onyx"
  }
}

variable "size" {
  type        = string
  description = <<-EOT
    T-shirt size that sets coherent defaults for every compute and data-plane knob:
      small  - pilots and small teams: up to ~200 users, < ~500k documents
      medium - typical department or company: ~200-1,000 users, ~0.5-2M documents
      large  - org-wide deployments: 1,000+ users, multi-million documents
    Any individual sizing variable set to a non-null value overrides its tier
    default. See the README for the full per-tier table.
  EOT
  default     = "medium"

  validation {
    condition     = contains(["small", "medium", "large"], var.size)
    error_message = "size must be one of: small, medium, large."
  }
}

# --- Network -----------------------------------------------------------------

variable "create_virtual_network" {
  type        = bool
  description = "Create the virtual network. False uses the subnets supplied below."
  default     = true

  validation {
    condition     = var.create_virtual_network || (var.virtual_network_id != null && var.aks_subnet_id != null && var.postgres_subnet_id != null && var.private_endpoint_subnet_id != null)
    error_message = "Bringing your own network needs virtual_network_id, aks_subnet_id, postgres_subnet_id and private_endpoint_subnet_id."
  }
}

variable "address_space" {
  type        = list(string)
  description = "Address space for the created virtual network"
  default     = ["10.0.0.0/16"]
}

variable "virtual_network_id" {
  type        = string
  description = "Existing virtual network. Required when create_virtual_network is false."
  default     = null
}

variable "aks_subnet_id" {
  type        = string
  description = "Existing subnet for the cluster nodes. Required when create_virtual_network is false."
  default     = null
}

variable "postgres_subnet_id" {
  type        = string
  description = "Existing subnet delegated to PostgreSQL Flexible Server. Required when create_virtual_network is false."
  default     = null
}

variable "private_endpoint_subnet_id" {
  type        = string
  description = "Existing subnet for private endpoints. Required when create_virtual_network is false."
  default     = null
}

variable "enable_nat_gateway" {
  type        = bool
  description = "Give the cluster a stable egress address through a NAT gateway. Only applies to a network this module creates."
  default     = true
}

# A supplied subnet may already carry a NAT gateway. Without this the
# composition would force AKS to manage outbound and throw away the stable
# address that gateway provides.
variable "aks_outbound_type" {
  type        = string
  description = "How cluster nodes reach the internet. Null derives it: userAssignedNATGateway when this module created the network with a NAT gateway, loadBalancer otherwise. Set it to userAssignedNATGateway when bringing a subnet that already has one."
  default     = null

  validation {
    condition     = var.aks_outbound_type == null || contains(["loadBalancer", "userAssignedNATGateway", "userDefinedRouting", "managedNATGateway"], var.aks_outbound_type)
    error_message = "aks_outbound_type must be one of: loadBalancer, userAssignedNATGateway, userDefinedRouting, managedNATGateway."
  }
}

# Off by default, unlike the AWS modules, because Azure needs a Network Watcher
# in the region and writes flow logs to a storage account. Turning this on
# creates a second storage account dedicated to logs.
variable "enable_flow_logs" {
  type        = bool
  description = "Send virtual network flow logs to a dedicated storage account. Requires a Network Watcher in this region; Azure names the one it creates \"NetworkWatcher_<region>\"."
  default     = false

  validation {
    condition     = !var.enable_flow_logs || var.create_virtual_network
    error_message = "enable_flow_logs only applies to a network this module creates. For a supplied network, configure the flow log against it directly, or the module would create a storage account and never write to it."
  }
}

variable "network_watcher_name" {
  type        = string
  description = "Network Watcher that owns the flow log. Null derives \"NetworkWatcher_<location>\"."
  default     = null
}

variable "network_watcher_resource_group_name" {
  type        = string
  description = "Resource group holding the Network Watcher"
  default     = "NetworkWatcherRG"
}

# --- Storage -----------------------------------------------------------------

variable "storage_account_name" {
  type        = string
  description = "Name of the file store account. Null derives one from the name, workspace and a short digest, because storage account names are globally unique and allow only 24 lowercase alphanumeric characters."
  default     = null
}

variable "storage_container_name" {
  type        = string
  description = "Blob container holding the Onyx file store"
  default     = "onyx-file-store"
}

variable "storage_account_replication_type" {
  type        = string
  description = "Replication for the file store account"
  default     = "ZRS"
}

variable "restrict_storage_to_cluster" {
  type        = bool
  description = "Let only the cluster subnet reach the storage account. Leave this off while running Terraform from outside the network, or the container becomes unreachable to whoever manages it."
  default     = false
}

# --- Postgres ----------------------------------------------------------------

variable "postgres_sku_name" {
  type        = string
  description = "Flexible server SKU. Null uses the t-shirt size default."
  default     = null
}

variable "postgres_storage_gb" {
  type        = number
  description = "Storage in GiB, off the fixed ladder Azure offers. Null uses the t-shirt size default."
  default     = null
}

variable "postgres_username" {
  type        = string
  description = "Administrator login for the database"
  default     = "psqladmin"
  sensitive   = true
}

variable "postgres_password" {
  type        = string
  description = "Administrator password. Supply it from a secret store. Required unless entra_database_authentication_only turns password logins off; enable_entra_database_authentication on its own only adds Entra logins alongside passwords."
  default     = null
  sensitive   = true

  validation {
    condition     = var.postgres_password != null || var.entra_database_authentication_only
    error_message = "postgres_password must be set. Azure rejects a server that accepts password logins but has no administrator password. Set entra_database_authentication_only to use Entra ID instead."
  }
}

variable "postgres_db_name" {
  type        = string
  description = "Database created on the server"
  default     = "postgres"
}

variable "postgres_engine_version" {
  type        = string
  description = "PostgreSQL major version"
  default     = "17"
}

variable "postgres_high_availability_enabled" {
  type        = bool
  description = "Run a standby in a second zone. Roughly doubles database cost."
  default     = false
}

variable "postgres_backup_retention_days" {
  type        = number
  description = "Days to retain automated backups"
  default     = 7
}

variable "enable_entra_database_authentication" {
  type        = bool
  description = "Accept Entra ID logins on the database, the analogue of the AWS module's IAM database authentication"
  default     = false
}

variable "entra_database_authentication_only" {
  type        = bool
  description = "Turn off password logins to the database so Entra ID is the only way in. Needs enable_entra_database_authentication and a database administrator."
  default     = false

  validation {
    condition     = !var.entra_database_authentication_only || var.enable_entra_database_authentication
    error_message = "entra_database_authentication_only requires enable_entra_database_authentication."
  }
}

variable "database_administrator_object_id" {
  type        = string
  description = "Object ID of the Entra principal to make database administrator. Required when entra_database_authentication_only is true."
  default     = null
}

variable "database_administrator_principal_name" {
  type        = string
  description = "Display name of the Entra database administrator"
  default     = null
}

variable "database_administrator_principal_type" {
  type        = string
  description = "What kind of Entra principal the database administrator is"
  default     = "Group"
}

variable "tenant_id" {
  type        = string
  description = "Entra ID tenant, required when enable_entra_database_authentication is true"
  default     = null
}

# --- Redis -------------------------------------------------------------------

variable "redis_sku_name" {
  type        = string
  description = "Cache tier. Null uses the t-shirt size default."
  default     = null
}

variable "redis_family" {
  type        = string
  description = "Cache family. Null uses the t-shirt size default."
  default     = null
}

variable "redis_capacity" {
  type        = number
  description = "Cache size within the family. Null uses the t-shirt size default."
  default     = null
}

# --- Cluster -----------------------------------------------------------------

variable "kubernetes_version" {
  type        = string
  description = "Kubernetes version for the control plane"
  default     = "1.33"
}

variable "main_node_vm_size" {
  type        = string
  description = "VM size for the system node pool. Null uses the t-shirt size default."
  default     = null
}

variable "main_node_min_count" {
  type        = number
  description = "Minimum nodes in the system pool. The autoscaler will not go below this, so raise it to keep always-on capacity for bursty work. Null uses the t-shirt size default."
  default     = null
}

variable "main_node_max_count" {
  type        = number
  description = "Maximum nodes in the system pool. Null uses the t-shirt size default."
  default     = null
}

# Azure has no managed OpenSearch, so this pool is where the document index
# runs. It is on by default, unlike the AWS module's equivalent.
variable "index_node_pool_enabled" {
  type        = bool
  description = "Create the document-index node pool"
  default     = true
}

variable "index_node_vm_size" {
  type        = string
  description = "VM size for the document-index pool. Memory-optimised, because the index is what needs it. Null uses the t-shirt size default."
  default     = null
}

variable "index_node_disk_size_gb" {
  type        = number
  description = "OS disk for document-index nodes. Null uses the t-shirt size default."
  default     = null
}

variable "private_cluster_enabled" {
  type        = bool
  description = "Give the API server a private endpoint only"
  default     = false
}

variable "api_server_authorized_ip_ranges" {
  type        = list(string)
  description = "CIDR ranges allowed to reach the public API server"
  default     = []
}

variable "allow_unrestricted_api_server_access" {
  type        = bool
  description = "Accept a public API server reachable from any address. Only for throwaway deployments; set api_server_authorized_ip_ranges or private_cluster_enabled instead."
  default     = false

  validation {
    condition     = var.allow_unrestricted_api_server_access || var.private_cluster_enabled || length(var.api_server_authorized_ip_ranges) > 0
    error_message = "A public API server with no authorized ranges is reachable from every address on the internet. Set api_server_authorized_ip_ranges, or private_cluster_enabled, or allow_unrestricted_api_server_access to record that the exposure is intended."
  }
}

variable "network_policy" {
  type        = string
  description = "NetworkPolicy engine. Null leaves enforcement off and existing policies inert."
  default     = null
}

variable "enable_gpu_node_pool" {
  type        = bool
  description = "Create a tainted GPU pool for the embedding model server"
  default     = false
}

variable "enable_sandbox_node_pool" {
  type        = bool
  description = "Create a tainted pool for Craft sandbox workloads"
  default     = false
}

variable "log_analytics_workspace_id" {
  type        = string
  description = "Workspace that receives control plane logs and container insights. Null sends neither."
  default     = null
}

variable "entra_rbac_admin_group_object_ids" {
  type        = list(string)
  description = "Entra ID groups granted cluster admin"
  default     = []
}

variable "additional_workload_service_account_names" {
  type        = list(string)
  description = "Further service accounts in the Onyx namespace that may use the workload identity. Use the rendered name for chart-created workloads such as onyx-sandbox-proxy."
  default     = []
}

variable "create_workload_namespace" {
  type        = bool
  description = "Create the namespace the workload service account lives in. Terraform has to make it: the Helm release that would otherwise is installed afterwards."
  default     = true
}

variable "create_workload_service_account" {
  type        = bool
  description = "Create the workload service account. Turn this off when the Helm chart already creates it."
  default     = true
}

# --- WAF ---------------------------------------------------------------------

variable "enable_waf" {
  type        = bool
  description = "Create a WAF policy to attach to an Application Gateway or Front Door route"
  default     = true
}

variable "waf_mode" {
  type        = string
  description = "Prevention blocks what the rules match; Detection only logs it"
  default     = "Prevention"
}

variable "waf_allowed_ip_cidrs" {
  type        = list(string)
  description = "Ranges allowed to reach the application. Empty disables the allowlist."
  default     = []
}

variable "waf_rate_limit_exempt_ip_cidrs" {
  type        = list(string)
  description = "Ranges exempt from the WAF rate limits"
  default     = []
}

# The NAT gateway is what the cluster's own outbound traffic comes from, so
# this is how a deployment that calls itself avoids rate-limiting itself.
variable "waf_trust_nat_gateway_ip" {
  type        = bool
  description = "Add the NAT gateway's egress address to the WAF allowlist and rate-limit exemptions"
  default     = false
}

variable "waf_geo_restriction_countries" {
  type        = list(string)
  description = "Two-letter country codes to block"
  default     = []
}

variable "waf_rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Requests per 5 minutes from one address before blocking"
  default     = 2000
}

variable "waf_api_rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Requests per 5 minutes from one address to the API path before blocking"
  default     = 1000
}

# --- Alerts ------------------------------------------------------------------

variable "action_group_ids" {
  type        = list(string)
  description = "Monitor action groups for the database and cache alerts. Empty = alerts exist but notify nothing."
  default     = []
}
