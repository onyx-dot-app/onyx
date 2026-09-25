variable "name" {
  type        = string
  description = "Instance ID, also the prefix for the alert policies"

  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]{0,38}[a-z0-9])?$", var.name))
    error_message = "name must be 1-40 lowercase letters, digits and hyphens, start with a letter and end with a letter or digit."
  }
}

variable "project_id" {
  type        = string
  description = "Project that holds the instance and its alert policies"
}

variable "region" {
  type        = string
  description = "Region for the instance, for example \"us-east1\""
}

# Take the vpc module's private_service_access_network_id rather than
# network_id: it carries the peering dependency, and the instance cannot be
# created until the Private Service Access connection exists.
variable "network_id" {
  type        = string
  description = "VPC network the instance is reachable from, as projects/<project>/global/networks/<name>. The network needs Private Service Access."

  validation {
    condition     = can(regex("^projects/[^/]+/global/networks/[^/]+$", var.network_id))
    error_message = "network_id must be a network ID of the form projects/<project>/global/networks/<name>."
  }
}

# BASIC is one node: a restart or zone failure flushes every queued Celery task.
variable "tier" {
  type        = string
  description = "STANDARD_HA keeps a replica in a second zone with automatic failover. BASIC is a single node."
  default     = "STANDARD_HA"

  validation {
    condition     = contains(["BASIC", "STANDARD_HA"], var.tier)
    error_message = "tier must be BASIC or STANDARD_HA."
  }
}

# Memorystore accepts 1 to 300 GiB on both tiers. 5 is the smallest size with
# committed-use pricing and the closest to the AWS module's cache.m5.large.
variable "memory_size_gb" {
  type        = number
  description = "Instance memory in GiB"
  default     = 5

  validation {
    condition     = var.memory_size_gb >= 1 && var.memory_size_gb <= 300 && floor(var.memory_size_gb) == var.memory_size_gb
    error_message = "memory_size_gb must be a whole number from 1 to 300."
  }
}

# Onyx runs Redis 7 in every other deployment path, so older engines are not offered.
variable "redis_version" {
  type        = string
  description = "Redis engine version"
  default     = "REDIS_7_2"

  validation {
    condition     = contains(["REDIS_7_0", "REDIS_7_2"], var.redis_version)
    error_message = "redis_version must be REDIS_7_0 or REDIS_7_2."
  }
}

# Off by default. TLS can only be chosen at creation, so toggling it replaces
# the instance and loses its data. With TLS on, set REDIS_SSL=true, and mount
# server_ca_certs into the pods with REDIS_SSL_CA_CERTS and
# REDIS_SSL_CERT_REQS=required, or Onyx's default of "none" encrypts without
# checking who it is talking to.
variable "transit_encryption_enabled" {
  type        = bool
  description = "Serve TLS on port 6378 instead of plaintext on 6379. Changing this replaces the instance."
  default     = false
}

variable "maxmemory_policy" {
  type        = string
  description = "What the instance does at its memory limit. volatile-lru only evicts keys that carry a TTL."
  default     = "volatile-lru"

  validation {
    condition = contains([
      "noeviction", "allkeys-lru", "allkeys-lfu", "allkeys-random",
      "volatile-lru", "volatile-lfu", "volatile-random", "volatile-ttl",
    ], var.maxmemory_policy)
    error_message = "maxmemory_policy must be one of: noeviction, allkeys-lru, allkeys-lfu, allkeys-random, volatile-lru, volatile-lfu, volatile-random, volatile-ttl."
  }

  # Celery broker keys carry no TTL, so the volatile-* policies never touch
  # them. An allkeys-* policy evicts queued tasks under memory pressure.
  validation {
    condition     = !startswith(var.maxmemory_policy, "allkeys-")
    error_message = "allkeys-* policies evict Celery broker keys, which have no TTL, and silently drop queued tasks. Use a volatile-* policy or noeviction."
  }
}

# RDB works on both tiers. On STANDARD_HA the snapshot runs on the replica, and
# it is what survives the loss of both nodes.
variable "persistence_enabled" {
  type        = bool
  description = "Take RDB snapshots so a full node loss restores from the last snapshot instead of starting empty"
  default     = true
}

variable "rdb_snapshot_period" {
  type        = string
  description = "How often to take an RDB snapshot when persistence is enabled"
  default     = "ONE_HOUR"

  validation {
    condition     = contains(["ONE_HOUR", "SIX_HOURS", "TWELVE_HOURS", "TWENTY_FOUR_HOURS"], var.rdb_snapshot_period)
    error_message = "rdb_snapshot_period must be ONE_HOUR, SIX_HOURS, TWELVE_HOURS or TWENTY_FOUR_HOURS."
  }
}

variable "maintenance_day" {
  type        = string
  description = "Day of the weekly one-hour maintenance window, in UTC"
  default     = "SUNDAY"

  validation {
    condition     = contains(["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"], var.maintenance_day)
    error_message = "maintenance_day must be a day of the week in upper case, for example SUNDAY."
  }
}

variable "maintenance_start_hour" {
  type        = number
  description = "Hour (0-23, UTC) the weekly maintenance window starts"
  default     = 4

  validation {
    condition     = var.maintenance_start_hour >= 0 && var.maintenance_start_hour <= 23 && floor(var.maintenance_start_hour) == var.maintenance_start_hour
    error_message = "maintenance_start_hour must be a whole number from 0 to 23."
  }
}

# Null lets Memorystore choose an unused /29 from the Private Service Access
# range. Set it to the name of an allocated range to pin where the instance lands.
variable "reserved_ip_range" {
  type        = string
  description = "Name of the Private Service Access range to place the instance in. Null lets Memorystore choose."
  default     = null
}

variable "deletion_protection" {
  type        = bool
  description = "Block terraform from destroying the instance. Set false and apply before a destroy."
  default     = true
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to the instance and its alert policies"
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.labels :
      can(regex("^[a-z][a-z0-9_-]{0,62}$", k)) && can(regex("^[a-z0-9_-]{0,63}$", v))
    ])
    error_message = "Label keys must start with a lowercase letter, and keys and values may only hold lowercase letters, digits, hyphens and underscores, up to 63 characters."
  }
}

# --- Alerts ------------------------------------------------------------------

variable "enable_alerts" {
  type        = bool
  description = "Create the Cloud Monitoring alert policies"
  default     = true
}

variable "notification_channels" {
  type        = list(string)
  description = "Notification channel IDs to route alerts to. Empty = alerts exist but notify nothing."
  default     = []
}

variable "memory_high_threshold_percent" {
  type        = number
  description = "Memory usage ratio warning threshold, in percent"
  default     = 80

  validation {
    condition     = var.memory_high_threshold_percent > 0 && var.memory_high_threshold_percent <= 100
    error_message = "memory_high_threshold_percent must be between 0 and 100."
  }
}

variable "memory_critical_threshold_percent" {
  type        = number
  description = "Memory usage ratio critical threshold, in percent. Near this the instance evicts or rejects writes, and the Celery fleet goes with it."
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
  description = "Main thread CPU threshold, in percent of one core"
  default     = 90

  validation {
    condition     = var.cpu_threshold_percent > 0 && var.cpu_threshold_percent <= 100
    error_message = "cpu_threshold_percent must be between 0 and 100."
  }
}

# Memorystore fixes maxclients at 65000 and does not allow a change, so the
# default is 80% of that. Onyx opens up to REDIS_POOL_MAX_CONNECTIONS (128) per
# process per pool, so a large Celery fleet reaches this sooner than expected.
variable "connected_clients_threshold" {
  type        = number
  description = "Connected clients before alerting. Memorystore caps connections at 65000."
  default     = 52000

  validation {
    condition     = var.connected_clients_threshold > 0 && var.connected_clients_threshold <= 65000
    error_message = "connected_clients_threshold must be between 1 and 65000, the fixed Memorystore maxclients."
  }
}

variable "evicted_keys_threshold" {
  type        = number
  description = "Evictions per 5 minutes before alerting. Zero alerts on the first eviction."
  default     = 0

  validation {
    condition     = var.evicted_keys_threshold >= 0
    error_message = "evicted_keys_threshold must be 0 or greater."
  }
}
