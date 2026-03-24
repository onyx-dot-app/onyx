variable "name" {
  description = "Name of the OpenSearch domain"
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC to deploy the OpenSearch domain into"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for the OpenSearch domain"
  type        = list(string)
}

variable "ingress_cidrs" {
  description = "CIDR blocks allowed to access OpenSearch"
  type        = list(string)
}

variable "engine_version" {
  description = "OpenSearch engine version (e.g., 2.17, 3.3)"
  type        = string
  default     = "3.3"
}

variable "instance_type" {
  description = "Instance type for data nodes"
  type        = string
  default     = "r8g.large.search"
}

variable "instance_count" {
  description = "Number of data nodes"
  type        = number
  default     = 3
}

variable "zone_awareness_enabled" {
  description = "Whether to enable zone awareness for the cluster"
  type        = bool
  default     = true
}

variable "availability_zone_count" {
  description = "Number of availability zones (2 or 3)"
  type        = number
  default     = 3
}

variable "dedicated_master_enabled" {
  description = "Whether to enable dedicated master nodes"
  type        = bool
  default     = true
}

variable "dedicated_master_type" {
  description = "Instance type for dedicated master nodes"
  type        = string
  default     = "m7g.large.search"
}

variable "dedicated_master_count" {
  description = "Number of dedicated master nodes (must be 3 or 5)"
  type        = number
  default     = 3
}

variable "multi_az_with_standby_enabled" {
  description = "Whether to enable Multi-AZ with Standby deployment"
  type        = bool
  default     = true
}

variable "warm_enabled" {
  description = "Whether to enable warm storage"
  type        = bool
  default     = false
}

variable "warm_type" {
  description = "Instance type for warm nodes"
  type        = string
  default     = "ultrawarm1.medium.search"
}

variable "warm_count" {
  description = "Number of warm nodes"
  type        = number
  default     = 2
}

variable "cold_storage_enabled" {
  description = "Whether to enable cold storage"
  type        = bool
  default     = false
}

variable "ebs_volume_type" {
  description = "EBS volume type (gp3, gp2, io1)"
  type        = string
  default     = "gp3"
}

variable "ebs_volume_size" {
  description = "EBS volume size in GB per node"
  type        = number
  default     = 512
}

variable "ebs_iops" {
  description = "IOPS for gp3/io1 volumes"
  type        = number
  default     = 3000
}

variable "ebs_throughput" {
  description = "Throughput in MiB/s for gp3 volumes"
  type        = number
  default     = 256
}

variable "kms_key_id" {
  description = "KMS key ID for encryption at rest (uses AWS managed key if not specified)"
  type        = string
  default     = null
}

variable "tls_security_policy" {
  description = "TLS security policy for HTTPS endpoints"
  type        = string
  default     = "Policy-Min-TLS-1-2-2019-07"
}

variable "internal_user_database_enabled" {
  description = "Whether to enable the internal user database for fine-grained access control"
  type        = bool
  default     = true
}

variable "master_user_name" {
  description = "Master user name for internal user database"
  type        = string
  default     = null
  sensitive   = true
}

variable "master_user_password" {
  description = "Master user password for internal user database"
  type        = string
  default     = null
  sensitive   = true
}

variable "master_user_arn" {
  description = "IAM ARN for the master user (used when internal_user_database_enabled is false)"
  type        = string
  default     = null
}

variable "advanced_options" {
  description = "Advanced options for OpenSearch"
  type        = map(string)
  default = {
    "indices.fielddata.cache.size"           = "20"
    "indices.query.bool.max_clause_count"    = "1024"
    "override_main_response_version"         = "false"
    "rest.action.multi.allow_explicit_index" = "true"
  }
}

variable "auto_tune_enabled" {
  description = "Whether to enable Auto-Tune"
  type        = bool
  default     = true
}

variable "auto_tune_rollback_on_disable" {
  description = "Whether to roll back Auto-Tune changes when disabled"
  type        = string
  default     = "NO_ROLLBACK"
}

variable "off_peak_window_enabled" {
  description = "Whether to enable off-peak window for maintenance"
  type        = bool
  default     = true
}

variable "off_peak_window_start_hours" {
  description = "Hour (UTC) when off-peak window starts (0-23)"
  type        = number
  default     = 6
}

variable "off_peak_window_start_minutes" {
  description = "Minutes when off-peak window starts (0-59)"
  type        = number
  default     = 0
}

variable "auto_software_update_enabled" {
  description = "Whether to enable automatic software updates"
  type        = bool
  default     = false
}

variable "enable_logging" {
  description = "Whether to enable CloudWatch logging"
  type        = bool
  default     = false
}

variable "create_service_linked_role" {
  description = "Whether to create the OpenSearch service-linked role (set to false if it already exists)"
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 30
}

variable "security_group_ids" {
  description = "Existing security group IDs to attach. If empty, a new SG is created."
  type        = list(string)
  default     = []
}

variable "log_group_name" {
  description = "CloudWatch log group name. Defaults to AWS console convention."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags to apply to OpenSearch resources"
  type        = map(string)
  default     = {}
}
