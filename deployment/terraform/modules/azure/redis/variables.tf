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
  description = "Azure region, for example \"eastus\""
}

# Azure sizes a cache by tier, family and capacity rather than by an instance
# type. Standard C3 is 6 GB with a replica, which is the size the AWS module
# defaults to.
variable "sku_name" {
  type        = string
  description = "Cache tier. Basic has no replica and no SLA. Standard adds a replica. Premium adds zone redundancy, persistence and clustering."
  default     = "Standard"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.sku_name)
    error_message = "sku_name must be Basic, Standard or Premium."
  }
}

variable "family" {
  type        = string
  description = "SKU family. C goes with Basic and Standard, P goes with Premium."
  default     = "C"

  validation {
    condition     = contains(["C", "P"], var.family)
    error_message = "family must be C or P."
  }

  validation {
    condition     = (var.sku_name == "Premium") == (var.family == "P")
    error_message = "Premium uses family P; Basic and Standard use family C."
  }
}

variable "capacity" {
  type        = number
  description = "Size within the family. C0 is 250 MB, C1 1 GB, C2 2.5 GB, C3 6 GB, C4 13 GB, C5 26 GB, C6 53 GB. P1 is 6 GB, P2 13 GB, P3 26 GB, P4 53 GB, P5 120 GB."
  default     = 3

  validation {
    condition     = floor(var.capacity) == var.capacity
    error_message = "capacity must be a whole number: the sizes are discrete steps, not a scale."
  }

  validation {
    condition     = var.family != "C" || (var.capacity >= 0 && var.capacity <= 6)
    error_message = "capacity must be between 0 and 6 for family C."
  }

  validation {
    condition     = var.family != "P" || (var.capacity >= 1 && var.capacity <= 5)
    error_message = "capacity must be between 1 and 5 for family P."
  }
}

variable "zones" {
  type        = list(string)
  description = "Availability zones to spread the cache across. Only Premium offers this."
  default     = []

  validation {
    condition     = length(var.zones) == 0 || var.sku_name == "Premium"
    error_message = "Only the Premium tier can be spread across availability zones."
  }
}

variable "minimum_tls_version" {
  type        = string
  description = "Minimum TLS version the cache accepts"
  default     = "1.2"

  validation {
    condition     = contains(["1.0", "1.1", "1.2"], var.minimum_tls_version)
    error_message = "minimum_tls_version must be one of: 1.0, 1.1, 1.2."
  }
}

# The AWS module takes an auth token as an input. Azure generates the access
# keys itself and offers no way to set them, so they come back as outputs
# instead. That removes the need for a caller to invent and store a password.
variable "access_keys_enabled" {
  type        = bool
  description = "Allow authenticating with the cache's generated access keys. Turn this off only once every client authenticates with Entra ID."
  default     = true

  validation {
    condition     = var.access_keys_enabled || var.enable_entra_authentication
    error_message = "Turning off access keys leaves no way to authenticate unless enable_entra_authentication is true."
  }
}

variable "enable_entra_authentication" {
  type        = bool
  description = "Accept Microsoft Entra ID logins. This is the analogue of the AWS module's IAM authentication."
  default     = false
}

variable "maxmemory_policy" {
  type        = string
  description = "What the cache does when it reaches its memory limit. Onyx uses Redis as a Celery broker, where an eviction silently drops a queued task, so watch the eviction alert if you move off the default."
  default     = "volatile-lru"

  validation {
    condition = contains([
      "noeviction", "allkeys-lru", "volatile-lru", "allkeys-random",
      "volatile-random", "volatile-ttl", "allkeys-lfu", "volatile-lfu",
    ], var.maxmemory_policy)
    error_message = "maxmemory_policy must be one of: noeviction, allkeys-lru, volatile-lru, allkeys-random, volatile-random, volatile-ttl, allkeys-lfu, volatile-lfu."
  }
}

variable "enable_private_endpoint" {
  type        = bool
  description = "Reach the cache over a private endpoint instead of its public hostname"
  default     = true

  validation {
    condition     = !var.enable_private_endpoint || var.private_endpoint_subnet_id != null
    error_message = "enable_private_endpoint requires private_endpoint_subnet_id."
  }

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

# privatelink.redis.cache.windows.net is a fixed name shared by every cache in
# a resource group, so a second module in the same group must be handed the
# zone the first one made rather than creating its own.
variable "private_dns_zone_id" {
  type        = string
  description = "Existing privatelink.redis.cache.windows.net zone to use. Null creates one."
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

# Redis runs its commands on one thread, so server load is the meaningful CPU
# signal, the same reason the AWS module alarms on EngineCPUUtilization rather
# than host CPU.
variable "server_load_threshold_percent" {
  type        = number
  description = "serverLoad threshold, the share of time the Redis server thread spent busy"
  default     = 90

  validation {
    condition     = var.server_load_threshold_percent > 0 && var.server_load_threshold_percent <= 100
    error_message = "server_load_threshold_percent must be between 0 and 100."
  }
}

# Azure exposes no swap metric, so this replaces the AWS module's swap alarm.
# It catches the same failure one step later: memory pressure that has started
# costing data.
variable "evicted_keys_threshold" {
  type        = number
  description = "Evictions per window before alerting. Zero alerts on the first eviction, which for a Celery broker means a dropped task."
  default     = 0

  validation {
    condition     = var.evicted_keys_threshold >= 0
    error_message = "evicted_keys_threshold must be 0 or greater."
  }
}
