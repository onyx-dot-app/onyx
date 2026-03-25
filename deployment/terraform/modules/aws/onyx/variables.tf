variable "name" {
  type        = string
  description = "Name of the Onyx resources. Example: 'onyx'"
  default     = "onyx"
}

variable "region" {
  type        = string
  description = "AWS region for all resources"
  default     = "us-west-2"
}

variable "create_vpc" {
  type        = bool
  description = "Whether to create a new VPC"
  default     = true
}

variable "vpc_id" {
  type        = string
  description = "ID of the VPC. Required if create_vpc is false."
  default     = null
}

variable "private_subnets" {
  type        = list(string)
  description = "Private subnets. Required if create_vpc is false."
  default     = [] # This will default to 0.0.0.0/0 if not provided
}

variable "public_subnets" {
  type        = list(string)
  description = "Public subnets. Required if create_vpc is false."
  default     = []
}

variable "vpc_cidr_block" {
  type        = string
  description = "VPC CIDR block. Required if create_vpc is false."
  default     = null
}

variable "s3_vpc_endpoint_id" {
  type        = string
  description = "ID of an existing S3 gateway VPC endpoint when reusing an existing VPC"
  default     = null

  validation {
    condition     = var.create_vpc || var.s3_vpc_endpoint_id != null
    error_message = "s3_vpc_endpoint_id must be provided when create_vpc is false."
  }
}

variable "tags" {
  type        = map(string)
  description = "Base tags applied to all AWS resources"
  default = {
    "project" = "onyx"
  }
}

variable "postgres_username" {
  type        = string
  description = "Username for the postgres database"
  default     = "postgres"
  sensitive   = true
}

variable "postgres_password" {
  type        = string
  description = "Password for the postgres database"
  default     = null
  sensitive   = true
}

variable "public_cluster_enabled" {
  type        = bool
  description = "Whether to enable public cluster access"
  default     = true
}

variable "private_cluster_enabled" {
  type        = bool
  description = "Whether to enable private cluster access"
  default     = false # Should be true for production, false for dev/staging
}

variable "cluster_endpoint_public_access_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to access the public EKS API endpoint"
  default     = []
}

variable "redis_auth_token" {
  type        = string
  description = "Authentication token for the Redis cluster"
  default     = null
  sensitive   = true
}

variable "enable_iam_auth" {
  type        = bool
  description = "Enable AWS IAM authentication for the RDS Postgres instance and wire IRSA policies"
  default     = false
}

variable "rds_db_connect_arn" {
  type        = string
  description = "Full rds-db:connect ARN to pass to the EKS module. Required when enable_rds_iam_auth is true."
  default     = null
}

# WAF Configuration Variables
variable "waf_rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Rate limit for requests per 5 minutes per IP address"
  default     = 2000
}

variable "waf_allowed_ip_cidrs" {
  type        = list(string)
  description = "Optional IPv4 CIDR ranges allowed through the WAF. Leave empty to disable IP allowlisting."
  default     = []
}

variable "waf_common_rule_set_count_rules" {
  type        = list(string)
  description = "Subrules within AWSManagedRulesCommonRuleSet to override to COUNT instead of BLOCK."
  default     = []
}

variable "waf_api_rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Rate limit for API requests per 5 minutes per IP address"
  default     = 1000
}

variable "waf_geo_restriction_countries" {
  type        = list(string)
  description = "List of country codes to block. Leave empty to disable geo restrictions"
  default     = []
}

variable "waf_enable_logging" {
  type        = bool
  description = "Enable WAF logging to CloudWatch"
  default     = true
}

variable "waf_log_retention_days" {
  type        = number
  description = "Number of days to retain WAF logs"
  default     = 90
}

# OpenSearch Configuration Variables
variable "enable_opensearch" {
  type        = bool
  description = "Whether to create an OpenSearch domain"
  default     = false
}

variable "opensearch_engine_version" {
  type        = string
  description = "OpenSearch engine version"
  default     = "3.3"
}

variable "opensearch_instance_type" {
  type        = string
  description = "Instance type for OpenSearch data nodes"
  default     = "r8g.large.search"
}

variable "opensearch_instance_count" {
  type        = number
  description = "Number of OpenSearch data nodes"
  default     = 3
}

variable "opensearch_dedicated_master_enabled" {
  type        = bool
  description = "Whether to enable dedicated master nodes for OpenSearch"
  default     = true
}

variable "opensearch_dedicated_master_type" {
  type        = string
  description = "Instance type for dedicated master nodes"
  default     = "m7g.large.search"
}

variable "opensearch_multi_az_with_standby_enabled" {
  type        = bool
  description = "Whether to enable Multi-AZ with Standby deployment"
  default     = true
}

variable "opensearch_ebs_volume_size" {
  type        = number
  description = "EBS volume size in GiB per OpenSearch node"
  default     = 512
}

variable "opensearch_ebs_throughput" {
  type        = number
  description = "Throughput in MiB/s for gp3 volumes"
  default     = 256
}

variable "opensearch_internal_user_database_enabled" {
  type        = bool
  description = "Whether to enable the internal user database for fine-grained access control"
  default     = true
}

variable "opensearch_master_user_name" {
  type        = string
  description = "Master user name for OpenSearch internal user database"
  default     = null
  sensitive   = true
}

variable "opensearch_master_user_password" {
  type        = string
  description = "Master user password for OpenSearch internal user database"
  default     = null
  sensitive   = true
}

variable "opensearch_domain_name" {
  type        = string
  description = "Override the OpenSearch domain name. If null, defaults to {name}-opensearch-{workspace}."
  default     = null
}

variable "opensearch_enable_logging" {
  type    = bool
  default = false
}

variable "opensearch_log_retention_days" {
  type        = number
  description = "Number of days to retain OpenSearch CloudWatch logs (0 = never expire)"
  default     = 0
}

variable "opensearch_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for OpenSearch. If empty, uses first 3 private subnets."
  default     = []
}
