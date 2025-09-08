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
