variable "identifier" {
  type        = string
  description = "Identifier for the database and related resources"
}

variable "db_name" {
  type        = string
  description = "Name of the database"
  default     = "postgres"
}

variable "instance_type" {
  type        = string
  description = "Instance type"
  default     = "db.t4g.large" # 2 vCPU and 8 GB of memory
}

variable "max_storage_gb" {
  type        = number
  description = "Upper limit in GB for RDS storage autoscaling. Null or 0 disables autoscaling."
  default     = null

  validation {
    # RDS requires the ceiling to be at least 10% above allocated storage.
    condition     = var.max_storage_gb == null || coalesce(var.max_storage_gb, 0) == 0 || coalesce(var.max_storage_gb, 0) >= ceil(1.1 * var.storage_gb)
    error_message = "max_storage_gb must be at least 10% greater than storage_gb (RDS requirement), or null/0 to disable autoscaling."
  }
}

variable "storage_type" {
  type        = string
  description = "EBS storage type for the RDS instance. Null keeps the instance's existing type (fleet DBs predate this variable and run gp2); prefer gp3 for new stacks."
  default     = null
}

variable "storage_gb" {
  type        = number
  description = "Storage size in GB"
  default     = 20
}

variable "engine_version" {
  type        = string
  description = "Engine version"
  default     = "17"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID. Unused when vpc_security_group_ids is set."
  default     = null
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnet IDs. Unused when db_subnet_group_name is set."
  default     = []
}

variable "ingress_cidrs" {
  type        = list(string)
  description = "Ingress CIDR blocks. Unused when vpc_security_group_ids is set."
  default     = []
}

variable "username" {
  type        = string
  description = "Username for the database"
  default     = "postgres"
  sensitive   = true
}

variable "password" {
  type        = string
  description = "Password for the database"
  default     = null
  sensitive   = true

  validation {
    condition     = var.password == null || !var.manage_master_user_password
    error_message = "password cannot be set when manage_master_user_password is true: RDS generates and rotates the master password in Secrets Manager, and the supplied value would be discarded."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to RDS resources"
  default     = {}
}

variable "enable_rds_iam_auth" {
  type        = bool
  description = "Enable AWS IAM database authentication for this RDS instance"
  default     = false
}

variable "backup_retention_period" {
  type        = number
  description = "Number of days to retain automated backups (0 to disable)"
  default     = 7

  validation {
    condition     = var.backup_retention_period >= 0 && var.backup_retention_period <= 35
    error_message = "backup_retention_period must be between 0 and 35 (AWS RDS limit)."
  }
}

variable "backup_window" {
  type        = string
  description = "Preferred UTC time window for automated backups (hh24:mi-hh24:mi)"
  default     = "03:00-04:00"

  validation {
    condition     = can(regex("^([01]\\d|2[0-3]):[0-5]\\d-([01]\\d|2[0-3]):[0-5]\\d$", var.backup_window))
    error_message = "backup_window must be in hh24:mi-hh24:mi format (e.g. \"03:00-04:00\")."
  }
}

# CloudWatch CPU alarm configuration
variable "cpu_alarm_threshold" {
  type        = number
  description = "CPU utilization percentage threshold for the CloudWatch alarm"
  default     = 80

  validation {
    condition     = var.cpu_alarm_threshold >= 0 && var.cpu_alarm_threshold <= 100
    error_message = "cpu_alarm_threshold must be between 0 and 100 (percentage)."
  }
}

variable "cpu_alarm_evaluation_periods" {
  type        = number
  description = "Number of consecutive periods the threshold must be breached before alarming"
  default     = 3

  validation {
    condition     = var.cpu_alarm_evaluation_periods >= 1
    error_message = "cpu_alarm_evaluation_periods must be at least 1."
  }
}

variable "cpu_alarm_period" {
  type        = number
  description = "Period in seconds over which the CPU metric is evaluated"
  default     = 300

  validation {
    condition     = var.cpu_alarm_period >= 60 && var.cpu_alarm_period % 60 == 0
    error_message = "cpu_alarm_period must be a multiple of 60 seconds and at least 60 (CloudWatch requirement)."
  }
}

variable "memory_alarm_threshold" {
  type        = number
  description = "Freeable memory threshold in bytes. Alarm fires when memory drops below this value."
  default     = 256000000 # 256 MB

  validation {
    condition     = var.memory_alarm_threshold > 0
    error_message = "memory_alarm_threshold must be greater than 0."
  }
}

variable "memory_alarm_evaluation_periods" {
  type        = number
  description = "Number of consecutive periods the threshold must be breached before alarming"
  default     = 3

  validation {
    condition     = var.memory_alarm_evaluation_periods >= 1
    error_message = "memory_alarm_evaluation_periods must be at least 1."
  }
}

variable "memory_alarm_period" {
  type        = number
  description = "Period in seconds over which the freeable memory metric is evaluated"
  default     = 300

  validation {
    condition     = var.memory_alarm_period >= 60 && var.memory_alarm_period % 60 == 0
    error_message = "memory_alarm_period must be a multiple of 60 seconds and at least 60 (CloudWatch requirement)."
  }
}

variable "read_iops_alarm_threshold" {
  type        = number
  description = "ReadIOPS threshold. Alarm fires when IOPS exceeds this value."
  default     = 3000

  validation {
    condition     = var.read_iops_alarm_threshold > 0
    error_message = "read_iops_alarm_threshold must be greater than 0."
  }
}

variable "iops_alarm_evaluation_periods" {
  type        = number
  description = "Number of consecutive periods the IOPS threshold must be breached before alarming"
  default     = 3

  validation {
    condition     = var.iops_alarm_evaluation_periods >= 1
    error_message = "iops_alarm_evaluation_periods must be at least 1."
  }
}

variable "iops_alarm_period" {
  type        = number
  description = "Period in seconds over which the IOPS metric is evaluated"
  default     = 300

  validation {
    condition     = var.iops_alarm_period >= 60 && var.iops_alarm_period % 60 == 0
    error_message = "iops_alarm_period must be a multiple of 60 seconds and at least 60 (CloudWatch requirement)."
  }
}

variable "alarm_actions" {
  type        = list(string)
  description = "List of ARNs to notify when the alarm transitions state (e.g. SNS topic ARNs)"
  default     = []
}

variable "free_storage_threshold_bytes" {
  type        = number
  description = "FreeStorageSpace alarm floor in bytes. Null = 15% of allocated storage_gb."
  default     = null

  validation {
    condition     = var.free_storage_threshold_bytes == null || var.free_storage_threshold_bytes > 0
    error_message = "free_storage_threshold_bytes must be null or greater than 0."
  }
}

variable "connections_alarm_threshold" {
  type        = number
  description = "DatabaseConnections alarm threshold (count)."
  default     = 500

  validation {
    condition     = var.connections_alarm_threshold > 0
    error_message = "connections_alarm_threshold must be greater than 0."
  }
}

# --- Multi-AZ / tenant-shard support -----------------------------------------
# Added for the multi-tenant shards, which need a standby, a shared parameter
# group, and the ability to sit inside networking that already exists.

variable "multi_az" {
  type        = bool
  description = "Run a standby in a second AZ. Doubles cost; required for anything serving tenants."
  default     = false
}

variable "iops" {
  type        = number
  description = "Provisioned IOPS for gp3/io1. Null uses the gp3 baseline for the volume size."
  default     = null
}

variable "storage_throughput" {
  type        = number
  description = "Provisioned throughput (MB/s) for gp3. Null uses the gp3 baseline."
  default     = null
}

variable "parameter_group_name" {
  type        = string
  description = "Existing DB parameter group. Null uses the engine default."
  default     = null
}

variable "performance_insights_enabled" {
  type        = bool
  description = "Enable Performance Insights."
  default     = false
}

variable "maintenance_window" {
  type        = string
  description = "Preferred maintenance window, e.g. sat:10:10-sat:10:40."
  default     = null
}

# When true, RDS generates and rotates the master password in Secrets Manager and
# any value passed to var.password is ignored.
variable "manage_master_user_password" {
  type        = bool
  description = "Let RDS generate and rotate the master password in Secrets Manager. Mutually exclusive with `password`."
  default     = false
}

variable "db_subnet_group_name" {
  type        = string
  description = "Existing subnet group to join. Null creates one from `subnet_ids`."
  default     = null
}

variable "vpc_security_group_ids" {
  type        = list(string)
  description = "Existing security groups to attach. Null creates one from `ingress_cidrs`."
  default     = null
}
