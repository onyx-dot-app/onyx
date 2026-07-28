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

variable "size" {
  type        = string
  description = <<-EOT
    T-shirt size that sets coherent defaults for every compute/data-plane knob
    (EKS node groups, RDS, ElastiCache, OpenSearch). Rough guide:
      small  — pilots and small teams: up to ~200 users, < ~500k documents
      medium — typical department/company: ~200-1,000 users, ~0.5-2M documents
      large  — org-wide deployments: 1,000+ users, multi-million documents
    Any individual sizing variable set to a non-null value overrides its tier
    default. See the README for the full per-tier table.
  EOT
  default     = "medium"

  validation {
    condition     = contains(["small", "medium", "large"], var.size)
    error_message = "size must be one of: small, medium, large."
  }
}

variable "main_node_instance_types" {
  type        = list(string)
  description = "Instance types for the main EKS node group. Null uses the t-shirt size default."
  default     = null
}

variable "main_node_min_size" {
  type        = number
  description = "Minimum main node group size (autoscaler floor). Null uses the t-shirt size default."
  default     = null
}

variable "main_node_max_size" {
  type        = number
  description = "Maximum main node group size. Null uses the t-shirt size default."
  default     = null
}

variable "vespa_node_enabled" {
  type        = bool
  description = "Whether to create the dedicated document-index node group. Null uses the t-shirt size default (small omits it: the small chart sizing fits the index on the main node, and on fresh clusters the group's taint would leave it idle anyway)."
  default     = null
}

variable "vespa_node_instance_types" {
  type        = list(string)
  description = "Instance types for the dedicated document-index (Vespa/OpenSearch STS) node group. Only relevant when running the index in-cluster. Null uses the t-shirt size default."
  default     = null
}

variable "vespa_node_disk_size_gb" {
  type        = number
  description = "Root EBS volume (GiB) for the document-index node. Null uses the t-shirt size default."
  default     = null
}

variable "postgres_instance_type" {
  type        = string
  description = "RDS instance class. Null uses the t-shirt size default."
  default     = null
}

variable "postgres_storage_gb" {
  type        = number
  description = "Initial RDS allocated storage in GiB (grows via autoscaling up to postgres_max_storage_gb; cannot shrink once applied). Null uses the t-shirt size default."
  default     = null
}

variable "postgres_max_storage_gb" {
  type        = number
  description = "RDS storage-autoscaling ceiling in GiB. 0 disables autoscaling; null uses the t-shirt size default."
  default     = null
}

variable "redis_instance_type" {
  type        = string
  description = "ElastiCache node type for the Redis replication group. Null uses the t-shirt size default."
  default     = null
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

variable "main_node_subnet_ids" {
  type        = list(string)
  description = "Explicit subnet IDs for the main node group. Takes precedence over main_node_private_subnets_only."
  default     = []
}

variable "main_node_private_subnets_only" {
  type        = bool
  description = "When true, pins the main node group to the VPC's private subnets so node egress always exits via the NAT gateway IP. Ignored if main_node_subnet_ids is set."
  default     = false
}

variable "redis_auth_token" {
  type        = string
  description = "Authentication token for the Redis cluster"
  default     = null
  sensitive   = true
}

variable "enable_craft" {
  type        = bool
  description = "Enable Craft infrastructure. Currently provisions a dedicated, IMDSv2-hardened Craft sandbox node group (labeled/tainted for sandbox pods)."
  default     = false
}

variable "craft_sandbox_node_instance_types" {
  type        = list(string)
  description = "Instance types for the Craft sandbox node group."
  default     = ["m5.large"]
}

variable "craft_sandbox_node_min_size" {
  type        = number
  description = "Min size of the Craft sandbox node group. Keep >= 1: cluster-autoscaler can only scale a group back up from zero with node-template label/taint ASG tags, which are not configured here, so a value of 0 would leave sandbox pods Pending after idle scale-down."
  default     = 1
}

variable "craft_sandbox_node_max_size" {
  type        = number
  description = "Max size of the Craft sandbox node group."
  default     = 4
}

variable "craft_sandbox_node_desired_size" {
  type        = number
  description = "Desired size of the Craft sandbox node group."
  default     = 1
}

variable "craft_sandbox_node_disk_size_gb" {
  type        = number
  description = "Root EBS volume (GiB) for Craft sandbox nodes. Size relative to the instance's vCPU and the sandbox pod's ephemeral-storage request (default 5Gi/pod). The default suits the default m5.large; raise it for larger instances."
  default     = 50

  validation {
    condition     = var.craft_sandbox_node_disk_size_gb >= 20
    error_message = "craft_sandbox_node_disk_size_gb must be at least 20 GiB; the AL2023 AMI and OS overlay consume ~8 GiB, leaving too little ephemeral storage for even one sandbox pod (5Gi request) below that threshold."
  }
}

variable "enable_iam_auth" {
  type        = bool
  description = "Enable AWS IAM authentication for the RDS Postgres instance and wire IRSA policies"
  default     = false
}

variable "irsa_additional_service_account_names" {
  type        = list(string)
  description = "Additional service accounts in the Onyx namespace that may assume the workload IRSA role. Use the rendered ServiceAccount name for chart-created workloads, such as onyx-sandbox-proxy, that also need RDS IAM auth."
  default     = []
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
  description = "Instance type for OpenSearch data nodes. Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_instance_count" {
  type        = number
  description = "Number of OpenSearch data nodes. Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_dedicated_master_enabled" {
  type        = bool
  description = "Whether to enable dedicated master nodes for OpenSearch"
  default     = true
}

variable "opensearch_dedicated_master_type" {
  type        = string
  description = "Instance type for dedicated master nodes. Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_multi_az_with_standby_enabled" {
  type        = bool
  description = "Whether to enable Multi-AZ with Standby deployment. Requires zone awareness and instance_count >= 3 when true. Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_zone_awareness_enabled" {
  type        = bool
  description = "Whether to spread OpenSearch data nodes across AZs. Must be false for single-data-node domains. Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_ebs_volume_size" {
  type        = number
  description = "EBS volume size in GiB per OpenSearch node. Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_ebs_iops" {
  type        = number
  description = "IOPS for gp3 volumes. Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_ebs_throughput" {
  type        = number
  description = "Throughput in MiB/s for gp3 volumes. Null uses the t-shirt size default."
  default     = null
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

# RDS Backup Configuration
variable "postgres_backup_retention_period" {
  type        = number
  description = "Number of days to retain automated RDS backups (0 to disable)"
  default     = 7
}

variable "postgres_backup_window" {
  type        = string
  description = "Preferred UTC time window for automated RDS backups (hh24:mi-hh24:mi)"
  default     = "03:00-04:00"
}

# EKS Control Plane Logging
variable "eks_cluster_enabled_log_types" {
  type        = list(string)
  description = "EKS control plane log types to enable (valid: api, audit, authenticator, controllerManager, scheduler)"
  default     = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
}

variable "eks_cloudwatch_log_group_retention_in_days" {
  type        = number
  description = "Number of days to retain EKS control plane logs in CloudWatch (0 = never expire)"
  default     = 30

  validation {
    condition     = contains([0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.eks_cloudwatch_log_group_retention_in_days)
    error_message = "Must be a valid CloudWatch retention value (0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653)."
  }
}
