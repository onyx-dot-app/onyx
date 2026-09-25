variable "name" {
  type        = string
  description = "Name prefix for every resource. Example: \"onyx\"."
  default     = "onyx"

  # The Memorystore instance ID is the tightest limit: "<name>-redis-<workspace>"
  # must fit in 40 characters, which leaves room for a workspace name of about 8.
  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,22}[a-z0-9])?$", var.name))
    error_message = "name must be 1-24 characters of lowercase letters, digits and hyphens, start with a letter and not end with a hyphen."
  }
}

variable "project_id" {
  type        = string
  description = "GCP project that holds every resource"

  validation {
    condition     = can(regex("^[a-z][-a-z0-9]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project ID: 6-30 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  type        = string
  description = "GCP region for all resources, for example \"us-east1\""

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "region must be a GCP region such as \"us-east1\", not a zone."
  }
}

variable "labels" {
  type        = map(string)
  description = "Base labels applied to every resource that supports them"
  # Add an owner label here if your asset inventory expects one. GCP labels
  # take only lowercase letters, digits, underscores and hyphens.
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

# One switch rather than one per module, so a teardown needs one apply with
# this false and nothing is left guarded by a flag someone forgot.
variable "deletion_protection" {
  type        = bool
  description = "Refuse to destroy the cluster, database, cache, bucket and Cloud Armor policy. Set false and apply before a destroy."
  default     = true
}

# A fresh project has most of these off, and every module fails on its first
# API call without them.
variable "enable_project_apis" {
  type        = bool
  description = "Enable the Google APIs the deployment uses. Turn this off when the project is managed elsewhere and the APIs are already on."
  default     = true
}

# --- Network -----------------------------------------------------------------

variable "create_network" {
  type        = bool
  description = "Create the VPC network. False uses the network, subnet and secondary ranges supplied below."
  default     = true

  validation {
    condition     = var.create_network || (var.network_id != null && var.subnet_id != null && var.pods_range_name != null && var.services_range_name != null)
    error_message = "Bringing your own network needs network_id, subnet_id, pods_range_name and services_range_name."
  }
}

variable "subnet_cidr" {
  type        = string
  description = "Primary range of the created subnet, used for node IPs"
  default     = "10.0.0.0/20"
}

variable "pods_cidr" {
  type        = string
  description = "Secondary range of the created subnet for pod IPs"
  default     = "10.4.0.0/14"
}

variable "services_cidr" {
  type        = string
  description = "Secondary range of the created subnet for service IPs"
  default     = "10.8.0.0/20"
}

variable "psa_prefix_length" {
  type        = number
  description = "Prefix length of the range reserved for Private Service Access (Cloud SQL, Memorystore)"
  default     = 16
}

# On by default, like the AWS modules and unlike Azure: GCP writes flow logs
# to Cloud Logging with no extra infrastructure.
variable "enable_flow_logs" {
  type        = bool
  description = "Write VPC flow logs for the subnet to Cloud Logging. Only applies to a network this module creates."
  default     = true
}

variable "network_id" {
  type        = string
  description = "Existing network, as projects/<project>/global/networks/<name>. It must already have Private Service Access and a Cloud NAT. Required when create_network is false."
  default     = null
}

variable "subnet_id" {
  type        = string
  description = "Existing subnet for the nodes. Required when create_network is false."
  default     = null
}

variable "pods_range_name" {
  type        = string
  description = "Secondary range on the existing subnet for pods. Required when create_network is false."
  default     = null
}

variable "services_range_name" {
  type        = string
  description = "Secondary range on the existing subnet for services. Required when create_network is false."
  default     = null
}

# --- Storage -----------------------------------------------------------------

variable "bucket_name" {
  type        = string
  description = "Name of the file store bucket. Null derives one from the name, workspace and a short digest, because bucket names are globally unique."
  default     = null
}

variable "bucket_force_destroy" {
  type        = bool
  description = "Delete every object when the bucket is destroyed. Off, so a destroy fails on a bucket that still holds files."
  default     = false
}

# --- Postgres ----------------------------------------------------------------

variable "postgres_tier" {
  type        = string
  description = "Cloud SQL machine tier, for example \"db-custom-2-8192\". Null uses the t-shirt size default."
  default     = null
}

variable "postgres_disk_size_gb" {
  type        = number
  description = "Initial data disk in GB. It grows on its own and never shrinks. Null uses the t-shirt size default."
  default     = null
}

variable "postgres_username" {
  type        = string
  description = "Login Onyx connects as. \"postgres\" is the user Cloud SQL ships and the chart's default."
  default     = "postgres"
  sensitive   = true
}

variable "postgres_password" {
  type        = string
  description = "Password for postgres_username. Supply it from a secret store."
  default     = null
  sensitive   = true

  validation {
    condition     = try(length(var.postgres_password) >= 8, false)
    error_message = "postgres_password must be set and at least 8 characters."
  }
}

# Not "postgres", the database Cloud SQL ships: Onyx gets a database of its
# own. Onyx reads POSTGRES_DB, which defaults to "postgres", so the chart
# values have to name this one.
variable "postgres_db_name" {
  type        = string
  description = "Database Onyx connects to. Set POSTGRES_DB to this value in the chart."
  default     = "onyx"
}

variable "postgres_database_version" {
  type        = string
  description = "Cloud SQL PostgreSQL version"
  default     = "POSTGRES_16"
}

variable "postgres_availability_type" {
  type        = string
  description = "ZONAL runs one instance. REGIONAL adds a standby in a second zone and roughly doubles database cost."
  default     = "ZONAL"
}

variable "postgres_max_connections" {
  type        = number
  description = "max_connections flag. Size it to pods x workers x (pool size + overflow). Changing it restarts the instance."
  default     = 500
}

# --- Redis -------------------------------------------------------------------

# On by default, unlike Azure. Memorystore for Redis is a single endpoint with
# 16 databases, so Onyx runs on it unchanged.
variable "enable_redis" {
  type        = bool
  description = "Create a Memorystore for Redis instance. False leaves Redis to the chart's in-cluster instance."
  default     = true
}

variable "redis_tier" {
  type        = string
  description = "STANDARD_HA keeps a replica in a second zone. BASIC is one node, and a restart loses every queued Celery task."
  default     = "STANDARD_HA"
}

variable "redis_memory_size_gb" {
  type        = number
  description = "Instance memory in GiB. Null uses the t-shirt size default."
  default     = null
}

variable "redis_transit_encryption_enabled" {
  type        = bool
  description = "Serve TLS on 6378. Onyx then needs REDIS_SSL=true; to verify the server, mount the redis_server_ca_certs output through the chart's redisTls. Changing this replaces the instance."
  default     = true
}

# --- Cluster -----------------------------------------------------------------

variable "kubernetes_version" {
  type        = string
  description = "Minimum control plane version, for example \"1.33\". Null takes the release channel default."
  default     = null
}

variable "release_channel" {
  type        = string
  description = "GKE release channel"
  default     = "REGULAR"
}

variable "main_node_machine_type" {
  type        = string
  description = "Machine type for the main pool. Null uses the t-shirt size default."
  default     = null
}

variable "main_node_min_count" {
  type        = number
  description = "Minimum nodes in the main pool, across all zones. Null uses the t-shirt size default."
  default     = null
}

variable "main_node_max_count" {
  type        = number
  description = "Maximum nodes in the main pool, across all zones. Null uses the t-shirt size default."
  default     = null
}

variable "main_node_disk_size_gb" {
  type        = number
  description = "Boot disk for main pool nodes"
  default     = 100
}

# GCP has no managed OpenSearch, so this pool is where the document index
# runs. It is on by default, unlike the AWS module's equivalent.
variable "index_node_pool_enabled" {
  type        = bool
  description = "Create the document-index node pool"
  default     = true
}

variable "index_node_machine_type" {
  type        = string
  description = "Machine type for the document-index pool. Memory-optimised, because the index is what needs it. Null uses the t-shirt size default."
  default     = null
}

variable "index_node_min_count" {
  type        = number
  description = "Minimum nodes in the document-index pool, across all zones"
  default     = 1
}

variable "index_node_max_count" {
  type        = number
  description = "Maximum nodes in the document-index pool, across all zones"
  default     = 3
}

variable "index_node_disk_size_gb" {
  type        = number
  description = "Boot disk for document-index nodes. Null uses the t-shirt size default."
  default     = null
}

variable "private_endpoint_enabled" {
  type        = bool
  description = "Serve the API server on its private address only"
  default     = false
}

variable "master_authorized_networks" {
  type = list(object({
    cidr_block   = string
    display_name = optional(string)
  }))
  description = "CIDR ranges allowed to reach the API server"
  default     = []
}

variable "allow_unrestricted_api_server_access" {
  type        = bool
  description = "Accept a public API server reachable from any address. Only for throwaway deployments; set master_authorized_networks or private_endpoint_enabled instead."
  default     = false

  validation {
    condition     = var.allow_unrestricted_api_server_access || var.private_endpoint_enabled || length(var.master_authorized_networks) > 0
    error_message = "A public API server with no authorized networks is reachable from every address on the internet. Set master_authorized_networks, or private_endpoint_enabled, or allow_unrestricted_api_server_access to record that the exposure is intended."
  }
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

variable "create_workload_namespace" {
  type        = bool
  description = "Create the namespace the workload service account lives in. Terraform has to make it: the Helm release that would otherwise is installed afterwards."
  default     = true
}

variable "workload_namespace" {
  type        = string
  description = "Namespace of the workload service account. Install the Helm release into it."
  default     = "onyx"
}

variable "workload_service_account_name" {
  type        = string
  description = "Kubernetes service account that gets the bucket grant. Point the chart's serviceAccount.name at it."
  default     = "onyx-workload-access"
}

# --- Cloud Armor -------------------------------------------------------------

variable "enable_cloud_armor" {
  type        = bool
  description = "Create a Cloud Armor policy to attach to an L7 load balancer through a BackendConfig or GCPBackendPolicy"
  default     = true
}

variable "cloud_armor_preview" {
  type        = bool
  description = "Log what the WAF and rate limit rules match instead of acting on it"
  default     = false
}

variable "cloud_armor_sensitivity" {
  type        = number
  description = "Sensitivity of the preconfigured WAF rules, 1 (fewest false positives) to 4"
  default     = 1
}

variable "cloud_armor_allowed_ip_cidrs" {
  type        = list(string)
  description = "Ranges allowed to reach the application. Empty disables the allowlist."
  default     = []
}

variable "cloud_armor_blocked_ip_cidrs" {
  type        = list(string)
  description = "Ranges refused with 403 before any other rule"
  default     = []
}

variable "cloud_armor_rate_limit_exempt_ip_cidrs" {
  type        = list(string)
  description = "Ranges exempt from the rate limits"
  default     = []
}

variable "cloud_armor_geo_restriction_countries" {
  type        = list(string)
  description = "Two-letter country codes to block"
  default     = []
}

variable "cloud_armor_rate_limit_threshold" {
  type        = number
  description = "Requests per 5 minutes from one address before it gets 429s"
  default     = 2000
}

variable "cloud_armor_api_rate_limit_threshold" {
  type        = number
  description = "Requests per 5 minutes from one address to the API path before it gets 429s"
  default     = 1000
}

variable "cloud_armor_adaptive_protection_enabled" {
  type        = bool
  description = "Enable Adaptive Protection layer 7 DDoS detection"
  default     = true
}

# --- Alerts ------------------------------------------------------------------

variable "enable_alerts" {
  type        = bool
  description = "Create the Cloud Monitoring alert policies for the database and cache"
  default     = true
}

variable "notification_channels" {
  type        = list(string)
  description = "Cloud Monitoring notification channel IDs for the database and cache alerts. Empty = alerts exist but notify nothing."
  default     = []
}
