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
  description = "VPC ID"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnet IDs"
}

variable "ingress_cidrs" {
  type        = list(string)
  description = "Ingress CIDR blocks"
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
}

variable "cpu_alarm_evaluation_periods" {
  type        = number
  description = "Number of consecutive periods the threshold must be breached before alarming"
  default     = 3
}

variable "cpu_alarm_period" {
  type        = number
  description = "Period in seconds over which the CPU metric is evaluated"
  default     = 300
}
