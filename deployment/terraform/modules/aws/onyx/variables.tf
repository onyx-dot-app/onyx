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

variable "single_nat_gateway" {
  type        = bool
  description = "Route all private subnets through one NAT gateway. Cheaper, but the NAT becomes a single-AZ dependency. False provisions one per AZ."
  default     = false
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
  # Add an `Owner` tag here if your asset inventory expects one. Everything set
  # here is stamped on every resource this module creates (EKS cluster + node
  # groups/ASGs, RDS, S3, Redis, OpenSearch, WAF, VPC).
  default = {
    "project" = "onyx"
  }
}

variable "size" {
  type        = string
  description = <<-EOT
    T-shirt size that sets coherent defaults for every compute/data-plane knob:
      small  - pilots and small teams: up to ~200 users, < ~500k documents
      medium - typical department/company: ~200-1,000 users, ~0.5-2M documents
      large  - org-wide deployments: 1,000+ users, multi-million documents
    Any individual sizing variable set to a non-null value overrides its tier
    default. See the README for the full per-tier table.
  EOT
  default     = "medium"

  validation {
    condition     = contains(["small", "medium", "large"], var.size)
    error_message = "size must be one of: small, medium, large."
  }
}


variable "postgres_instance_type" {
  type        = string
  description = "RDS instance class Null uses the t-shirt size default."
  default     = null
}

variable "postgres_storage_gb" {
  type        = number
  description = "Initial RDS allocated storage in GiB (grows via autoscaling up to postgres_max_storage_gb; cannot shrink once applied). Null uses the t-shirt size default."
  default     = null
}

variable "postgres_max_storage_gb" {
  type        = number
  description = "RDS storage-autoscaling ceiling in GiB. Null or 0 disables autoscaling. Null uses the t-shirt size default."
  default     = null
}

variable "postgres_storage_type" {
  type        = string
  description = "EBS storage type for the RDS instance. Null keeps the instance's existing type (fleet DBs predate this variable and run gp2)."
  default     = null
}

variable "postgres_multi_az" {
  type        = bool
  description = "Run an RDS standby in a second AZ. Roughly doubles database cost. Set true if a standby already exists, or Terraform removes it."
  default     = false
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
  default     = true # Should be true for production, false for dev/staging
}

variable "cluster_endpoint_public_access_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to access the public EKS API endpoint. Empty denies all public access; set this if public_cluster_enabled is true."
  default     = []
}

variable "redis_auth_token" {
  type        = string
  description = "Authentication token for the Redis cluster"
  default     = null
  sensitive   = true
}

variable "redis_instance_type" {
  type        = string
  description = "ElastiCache node type for the Redis replication group Null uses the t-shirt size default."
  default     = null
}

variable "enable_iam_auth" {
  type        = bool
  description = "Enable AWS IAM authentication for the RDS Postgres instance and wire IRSA policies"
  default     = false
}

variable "enable_redis_iam_auth" {
  type        = bool
  description = "Enable AWS IAM authentication for the Redis ElastiCache instance"
  default     = false
}

variable "enable_upload_bucket" {
  type        = bool
  description = "Provision an additional S3 bucket dedicated to uploads"
  default     = false
}

variable "irsa_additional_service_account_names" {
  type        = list(string)
  description = "Additional service accounts in the Onyx namespace that may assume the workload IRSA role. Use the rendered ServiceAccount name for chart-created workloads, such as onyx-sandbox-proxy, that also need RDS IAM auth."
  default     = []
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

variable "s3_additional_policy_documents" {
  type        = list(string)
  description = "IAM policy documents (JSON strings) merged into the main bucket's policy. See additional_policy_documents on the s3 module."
  default     = []
}

variable "s3_upload_additional_policy_documents" {
  type        = list(string)
  description = "IAM policy documents (JSON strings) merged into the upload bucket's policy. Only used when enable_upload_bucket is true."
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

variable "waf_trust_vpc_nat_gateway_ips" {
  type        = bool
  description = "Add public IPs from Terraform-managed VPC NAT gateways to the WAF allowlist and rate-limit exemptions."
  default     = false
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

variable "waf_rate_limit_exempt_ip_cidrs" {
  type        = list(string)
  description = "Optional IPv4 CIDR ranges exempt from WAF rate limiting rules."
  default     = []
}

variable "waf_anonymous_ip_list_count_only" {
  type        = bool
  description = "If true, set AWSManagedRulesAnonymousIpList to COUNT instead of BLOCK."
  default     = false
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
  description = "Number of days to retain WAF logs. Default 400 = 12 months + 30-day buffer for the common twelve-month log-retention control."
  default     = 400
}

variable "main_node_instance_types" {
  type        = list(string)
  description = "Instance types for the main EKS node group Null uses the t-shirt size default."
  default     = null
}

variable "vespa_node_enabled" {
  type        = bool
  description = "Whether to create the dedicated document-index node group. Disable for customers on a managed OpenSearch domain — the group otherwise sits idle. Null uses the t-shirt size default."
  default     = null
}

variable "vespa_node_instance_types" {
  type        = list(string)
  description = "Instance types for the Vespa EKS node group Null uses the t-shirt size default."
  default     = null
}

variable "vespa_node_disk_size_gb" {
  type        = number
  description = "Root EBS volume (GiB) for the Vespa/document-index node. Null keeps the node-group default (100 GiB). Null uses the t-shirt size default."
  default     = null
}

variable "vespa_node_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for the Vespa node group (must be in same AZ as Vespa PV)"
  default     = []
}

variable "main_node_subnet_ids" {
  type        = list(string)
  description = "Explicit subnet IDs for the main node group. Takes precedence over main_node_private_subnets_only."
  default     = []
}

variable "main_node_private_subnets_only" {
  type        = bool
  description = "When true, pins the main node group to the VPC's private subnets so node egress always exits via the NAT EIP. Ignored if main_node_subnet_ids is set."
  default     = false
}

variable "main_node_min_size" {
  type        = number
  description = "Minimum number of nodes in the main node group. The cluster-autoscaler will not scale below this, so raise it to guarantee always-on baseline capacity for bursty workloads. Null uses the t-shirt size default."
  default     = null
}

variable "main_node_max_size" {
  type        = number
  description = "Maximum number of nodes the main node group may scale up to. Null uses the t-shirt size default."
  default     = null
}

variable "enable_gpu_node" {
  type        = bool
  description = "Whether to create a dedicated, tainted GPU node group for the embedding model server. Opt-in per customer."
  default     = false
}

variable "gpu_node_instance_types" {
  type        = list(string)
  description = "Instance types for the GPU node group. g4dn.xlarge (1x NVIDIA T4) is sufficient for the embedding model."
  default     = ["g4dn.xlarge"]
}

variable "enable_craft" {
  type        = bool
  description = "Create a dedicated Craft sandbox node group (labeled onyx.app/workload=sandbox, tainted workload=sandbox:NoSchedule, IMDSv2 hop-limit 1). Opt-in per workspace."
  default     = false
}

variable "craft_sandbox_node_instance_types" {
  type        = list(string)
  description = "Instance types for the Craft sandbox node group."
  default     = ["m8i.2xlarge"]
}

variable "craft_sandbox_node_min_size" {
  type        = number
  description = "Min size of the Craft sandbox node group."
  default     = 1
}

variable "craft_sandbox_node_max_size" {
  type        = number
  description = "Max size of the Craft sandbox node group (cluster-autoscaler scales between min and max)."
  default     = 7
}

variable "craft_sandbox_node_desired_size" {
  type        = number
  description = "Desired size of the Craft sandbox node group."
  default     = 1
}

variable "craft_sandbox_node_disk_size_gb" {
  type        = number
  description = "Root EBS volume (GiB) for Craft sandbox nodes. Size so ephemeral-storage is not the binding scheduling dimension (~5.5Gi reserved per sandbox pod); AMI default ~20Gi caps a node at ~3 sandboxes."
  default     = 200
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
  description = "Instance type for OpenSearch data nodes Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_instance_count" {
  type        = number
  description = "Number of OpenSearch data nodes Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_dedicated_master_enabled" {
  type        = bool
  description = "Whether to enable dedicated master nodes for OpenSearch"
  default     = true
}

variable "opensearch_dedicated_master_type" {
  type        = string
  description = "Instance type for dedicated master nodes Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_multi_az_with_standby_enabled" {
  type        = bool
  description = "Whether to enable Multi-AZ with Standby deployment Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_zone_awareness_enabled" {
  type        = bool
  description = "Whether to enable zone awareness for the OpenSearch cluster Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_ebs_iops" {
  type        = number
  description = "IOPS for OpenSearch gp3/io1 volumes Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_ebs_volume_size" {
  type        = number
  description = "EBS volume size in GiB per OpenSearch node Null uses the t-shirt size default."
  default     = null
}

variable "opensearch_ebs_throughput" {
  type        = number
  description = "Throughput in MiB/s for gp3 volumes Null uses the t-shirt size default."
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

variable "postgres_connections_alarm_threshold" {
  type        = number
  description = "DatabaseConnections alarm threshold. Size against the instance's actual max_connections — the postgres-module default (500) is below steady-state pool usage on large clusters."
  default     = 500
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
variable "eks_cluster_version" {
  type        = string
  description = "EKS control plane Kubernetes version for this cluster (hop one cluster at a time; see the eks module default)"
  default     = "1.33"
}

variable "eks_cluster_enabled_log_types" {
  type        = list(string)
  description = "EKS control plane log types to enable (valid: api, audit, authenticator, controllerManager, scheduler)"
  default     = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
}

variable "eks_cloudwatch_log_group_retention_in_days" {
  type        = number
  description = "Number of days to retain EKS control plane logs in CloudWatch (0 = never expire). Default 400 = 12 months + 30-day buffer for the common twelve-month log-retention control."
  default     = 400

  validation {
    condition     = contains([0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.eks_cloudwatch_log_group_retention_in_days)
    error_message = "Must be a valid CloudWatch retention value (0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653)."
  }
}

variable "enable_network_policy" {
  type        = bool
  description = "Adopt the VPC CNI addon and enable Kubernetes NetworkPolicy enforcement. Off by default: the addon stays unmanaged and existing NetworkPolicies remain inert. Only enable per cluster once its policies are known-safe."
  default     = false
}

variable "vpc_cni_addon_version" {
  type        = string
  description = "VPC CNI addon version to pin when enable_network_policy is true. Set to the cluster's currently-running version (aws eks describe-addon --addon-name vpc-cni) to avoid an unintended CNI upgrade on adoption."
  default     = "v1.20.4-eksbuild.2"
}

variable "alarm_actions" {
  type        = list(string)
  description = "SNS topic ARNs for RDS/ElastiCache CloudWatch alarm + ok actions. Empty = infra alarms exist but notify nothing."
  default     = []
}
