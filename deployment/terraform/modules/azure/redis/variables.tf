variable "name" {
  type        = string
  description = "Name of the cache and the resources named after it"

  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]$", var.name))
    error_message = "name must be 2-63 characters of letters, digits and hyphens, and must start and end with a letter or digit."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the cache"
}

variable "location" {
  type        = string
  description = "Azure region, for example \"eastus2\""
}

# Azure Managed Redis sizes by a single SKU name rather than the tier, family
# and capacity that Azure Cache for Redis used. The prefix picks the shape:
# Balanced is the general purpose one, MemoryOptimized trades vCPU for RAM,
# ComputeOptimized does the reverse, FlashOptimized puts colder keys on NVMe.
variable "sku_name" {
  type        = string
  description = "Managed Redis SKU, for example \"Balanced_B5\" for 5 GB. The number is roughly the memory in GB."
  default     = "Balanced_B5"

  # Each family uses its own letter, so the letter and the family have to agree:
  # Balanced_C3 is not a size, it is two families spliced together. Checking the
  # pairing catches that without pinning an exact SKU list that goes stale every
  # time Azure adds a size.
  validation {
    condition     = can(regex("^(Balanced_B|MemoryOptimized_M|ComputeOptimized_X|FlashOptimized_A)[0-9]+$", var.sku_name))
    error_message = "sku_name must pair the family with its own letter: Balanced_B*, MemoryOptimized_M*, ComputeOptimized_X* or FlashOptimized_A* (for example Balanced_B5)."
  }
}

variable "high_availability_enabled" {
  type        = bool
  description = "Keep a replica in another availability zone. Roughly doubles cost, and is what makes the cache survive a zone failure."
  default     = false
}

# OSSCluster shards across nodes and needs a cluster-aware client. Onyx uses
# Redis as a Celery broker through redis-py, which is not, so the single-endpoint
# mode is the compatible default.
variable "clustering_policy" {
  type        = string
  description = "EnterpriseCluster presents one endpoint and works with ordinary Redis clients. OSSCluster shards and requires a cluster-aware client."
  default     = "EnterpriseCluster"

  validation {
    condition     = contains(["EnterpriseCluster", "OSSCluster"], var.clustering_policy)
    error_message = "clustering_policy must be EnterpriseCluster or OSSCluster."
  }
}

# Redis Enterprise names these differently from Redis itself: VolatileLRU rather
# than volatile-lru.
variable "eviction_policy" {
  type        = string
  description = "What the cache does at its memory limit. Onyx uses Redis as a Celery broker, where an eviction silently drops a queued task, so watch the eviction alert if you move off the default."
  default     = "VolatileLRU"

  validation {
    condition = contains([
      "NoEviction", "AllKeysLRU", "AllKeysLFU", "AllKeysRandom",
      "VolatileLRU", "VolatileLFU", "VolatileRandom", "VolatileTTL",
    ], var.eviction_policy)
    error_message = "eviction_policy must be one of: NoEviction, AllKeysLRU, AllKeysLFU, AllKeysRandom, VolatileLRU, VolatileLFU, VolatileRandom, VolatileTTL."
  }
}

# Azure generates the access keys and offers no way to set them, so they come
# back as outputs rather than going in as a variable.
variable "access_keys_enabled" {
  type        = bool
  description = "Allow authenticating with the generated access keys. Turn this off only once every client authenticates with Entra ID through an access policy assignment."
  default     = true
}

variable "enable_private_endpoint" {
  type        = bool
  description = "Reach the cache over a private endpoint instead of its public hostname"
  default     = true

  validation {
    condition     = !var.enable_private_endpoint || var.private_endpoint_subnet_id != null
    error_message = "enable_private_endpoint requires private_endpoint_subnet_id."
  }

  # The virtual network is only used to link a zone this module creates. A
  # caller reusing an existing zone has already linked it, so demanding the
  # network there rejects a configuration that is complete.
  validation {
    condition     = !var.enable_private_endpoint || var.private_dns_zone_id != null || var.virtual_network_id != null
    error_message = "enable_private_endpoint requires virtual_network_id so the private DNS zone can be linked to it, unless private_dns_zone_id points at a zone that is already linked."
  }
}

variable "private_endpoint_subnet_id" {
  type        = string
  description = "Subnet that holds the private endpoint. It needs private_endpoint_network_policies set to Disabled."
  default     = null
}

variable "virtual_network_id" {
  type        = string
  description = "Virtual network linked to the private DNS zone, so clients in it resolve the cache's private address"
  default     = null
}

# privatelink.redis.azure.net is a fixed name shared by every managed cache in a
# resource group, so a second module in the same group must be handed the zone
# the first one made rather than creating its own.
variable "private_dns_zone_id" {
  type        = string
  description = "Existing privatelink.redis.azure.net zone to use. Null creates one."
  default     = null
}

variable "public_network_access_enabled" {
  type        = bool
  description = "Allow the cache's public hostname to be reached. Null follows enable_private_endpoint: private endpoint on means public access off."
  default     = null

  validation {
    condition     = var.enable_private_endpoint || var.public_network_access_enabled != false
    error_message = "Turning off both the private endpoint and public network access leaves a cache nothing can reach. Keep enable_private_endpoint on, or allow public access."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to the cache and its alerts"
  default     = {}
}

# --- Alerts ------------------------------------------------------------------

variable "action_group_ids" {
  type        = list(string)
  description = "Monitor action groups to notify. Empty = alerts exist but notify nothing."
  default     = []
}

variable "memory_high_threshold_percent" {
  type        = number
  description = "usedmemorypercentage warning threshold"
  default     = 80

  validation {
    condition     = var.memory_high_threshold_percent > 0 && var.memory_high_threshold_percent <= 100
    error_message = "memory_high_threshold_percent must be between 0 and 100."
  }
}

variable "memory_critical_threshold_percent" {
  type        = number
  description = "usedmemorypercentage critical threshold. Near this the cache starts evicting or rejecting writes, and the Celery fleet goes with it."
  default     = 90

  validation {
    condition     = var.memory_critical_threshold_percent > 0 && var.memory_critical_threshold_percent <= 100
    error_message = "memory_critical_threshold_percent must be between 0 and 100."
  }

  validation {
    condition     = var.memory_critical_threshold_percent >= var.memory_high_threshold_percent
    error_message = "memory_critical_threshold_percent must be at least memory_high_threshold_percent, otherwise the critical alert fires before the warning one."
  }
}

variable "cpu_threshold_percent" {
  type        = number
  description = "percentProcessorTime threshold. Redis Enterprise reports processor time rather than the single-thread server load the old service exposed."
  default     = 90

  validation {
    condition     = var.cpu_threshold_percent > 0 && var.cpu_threshold_percent <= 100
    error_message = "cpu_threshold_percent must be between 0 and 100."
  }
}

variable "evicted_keys_threshold" {
  type        = number
  description = "Evictions per window before alerting. Zero alerts on the first eviction, which for a Celery broker means a dropped task."
  default     = 0

  validation {
    condition     = var.evicted_keys_threshold >= 0
    error_message = "evicted_keys_threshold must be 0 or greater."
  }
}
