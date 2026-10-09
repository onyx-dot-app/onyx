variable "name" {
  description = "The name of the redis instance"
  type        = string
}

variable "vpc_id" {
  description = "The ID of the vpc to deploy the redis instance into"
  type        = string
}

variable "subnet_ids" {
  description = "The subnets of the vpc to deploy into"
  type        = list(string)
}

variable "ingress_cidrs" {
  description = "CIDR block to allow ingress from"
  type        = list(string)
}

variable "instance_type" {
  description = "The instance type of the redis instance"
  type        = string
  default     = "cache.m5.large" # 2 vCPU and 6 GB of memory
}

variable "transit_encryption_enabled" {
  description = "Enable transit encryption (SSL/TLS) for Redis"
  type        = bool
  default     = true
}

variable "auth_token" {
  description = "The password used to access a password protected server. Set to null when using IAM authentication."
  type        = string
  default     = null
  sensitive   = true
}

variable "enable_redis_iam_auth" {
  description = "Omit the auth token so the replication group can be used with IAM authentication. This module does not create the ElastiCache user or user group; provision and associate those separately before enabling."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags to apply to ElastiCache resources"
  type        = map(string)
  default     = {}
}

variable "security_group_ids" {
  description = "Existing security group IDs to attach. If non-empty, the module skips creating its own SG."
  type        = list(string)
  default     = []
}

variable "alarm_actions" {
  description = "SNS topic ARNs to notify on CloudWatch alarm/ok. Empty = alarms exist but notify nothing."
  type        = list(string)
  default     = []
}

variable "memory_high_threshold_percent" {
  description = "DatabaseMemoryUsagePercentage warning threshold."
  type        = number
  default     = 80
}

variable "memory_critical_threshold_percent" {
  description = "DatabaseMemoryUsagePercentage critical threshold — near this, Redis rejects writes."
  type        = number
  default     = 90
}

variable "engine_cpu_threshold_percent" {
  description = "EngineCPUUtilization (Redis engine thread) alarm threshold."
  type        = number
  default     = 90
}

variable "swap_usage_threshold_bytes" {
  description = "SwapUsage alarm threshold in bytes (default 50 MiB)."
  type        = number
  default     = 52428800
}
