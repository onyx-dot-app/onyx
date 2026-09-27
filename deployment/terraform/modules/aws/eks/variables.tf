variable "cluster_name" {
  type        = string
  description = "The name of the cluster"
}

variable "cluster_version" {
  type        = string
  description = "The EKS version of the cluster"
  default     = "1.33"
}

variable "vpc_id" {
  type        = string
  description = "The ID of the VPC"
}

variable "subnet_ids" {
  type        = list(string)
  description = "The IDs of the subnets"
}

variable "public_cluster_enabled" {
  type        = bool
  description = "Whether to enable public cluster access"
  default     = true
}

variable "private_cluster_enabled" {
  type        = bool
  description = "Whether to enable private cluster access"
  default     = true
}

variable "cluster_endpoint_public_access_cidrs" {
  type        = list(string)
  description = "List of CIDR blocks allowed to access the public EKS API endpoint. Empty denies all public access; set this if public_cluster_enabled is true."
  default     = []
}

variable "main_node_instance_types" {
  type        = list(string)
  description = "Instance types for the main node group"
  default     = ["m7i.4xlarge"]
}

variable "vespa_node_enabled" {
  type        = bool
  description = "Whether to create the dedicated Vespa/document-index node group. Disable when the index runs off-cluster (managed OpenSearch) or fits on the main node group."
  default     = true
}

variable "vespa_node_instance_types" {
  type        = list(string)
  description = "Instance types for the Vespa node group"
  default     = ["m6i.2xlarge"]
}

variable "vespa_node_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for the Vespa node group (must be in same AZ as Vespa PV). If not specified, uses all cluster subnets."
  default     = []
}

variable "main_node_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for the main node group. If not specified, uses all cluster subnets. Pin to private subnets to keep node egress on the NAT EIP across replacements."
  default     = []
}

variable "main_node_min_size" {
  type        = number
  description = "Minimum number of nodes in the main node group. The cluster-autoscaler will not scale below this, so raise it to guarantee always-on baseline capacity for bursty workloads. Null keeps the node-group default."
  default     = null
}

variable "vespa_node_disk_size_gb" {
  type        = number
  description = "Root EBS volume (GiB) for the Vespa/document-index node. Null keeps the node-group default."
  default     = null
}

variable "main_node_max_size" {
  type        = number
  description = "Maximum number of nodes the main node group may scale up to. Null keeps the node-group default."
  default     = null
}

variable "enable_gpu_node" {
  type        = bool
  description = "Whether to create a dedicated, tainted GPU node group for the embedding model server. Opt-in per customer."
  default     = false

  validation {
    condition     = !var.enable_gpu_node || !contains(keys(var.eks_managed_node_groups), "gpu")
    error_message = "enable_gpu_node injects a node group under the key \"gpu\", which eks_managed_node_groups already defines. Rename your group so the GPU group does not replace it."
  }
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

  validation {
    condition     = !var.enable_craft || !contains(keys(var.eks_managed_node_groups), "sandbox")
    error_message = "enable_craft injects a node group under the key \"sandbox\", which eks_managed_node_groups already defines. Rename your group so the Craft group does not replace it."
  }
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
  description = "Root EBS volume (GiB) for Craft sandbox nodes. Size so ephemeral-storage is NOT the binding scheduling dimension: each sandbox pod reserves ~5.5Gi eph, so allow (max_sandboxes_per_node * 5.5Gi) + system/image headroom. The AMI default (~20Gi) caps a node at ~3 sandboxes despite ~7 by CPU."
  default     = 200

  validation {
    condition     = var.craft_sandbox_node_disk_size_gb >= 20
    error_message = "craft_sandbox_node_disk_size_gb must be at least 20 GiB; the AL2023 AMI and OS overlay consume ~8 GiB, leaving too little ephemeral storage for even one sandbox pod (5Gi request) below that threshold."
  }
}

variable "eks_managed_node_groups" {
  type        = map(any)
  description = "EKS managed node groups with EBS volume configuration"
  default = {
    # Main node group for all pods except Vespa
    main = {
      name           = "main-node-group"
      instance_types = null # Will be set from var.main_node_instance_types
      min_size       = 1
      max_size       = 5
      # EBS volume configuration
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 100
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
            iops                  = 3000
            throughput            = 125
          }
        }
      }
      # No taints for main node group
      taints = []
    }
    # Vespa dedicated node group
    vespa = {
      name           = "vespa-node-group"
      instance_types = null # Will be set from var.vespa_node_instance_types
      min_size       = 1
      max_size       = 1
      # Larger EBS volume for Vespa storage
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 100
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
            iops                  = 3000
            throughput            = 125
          }
        }
      }
      # Taint to ensure only Vespa pods can schedule here
      taints = [
        {
          key    = "vespa-dedicated"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    }
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to the resources"
  default     = {}
}

variable "create_gp3_storage_class" {
  type        = bool
  description = "Whether to create the gp3 storage class. The gp3 storage class will be patched to make it default and allow volume expansion."
  default     = true
}

variable "s3_bucket_names" {
  type        = list(string)
  description = "List of S3 bucket names that workloads in this cluster are allowed to access via IRSA. If empty, no S3 access role/policy/service account will be created."
  default     = []
}

variable "irsa_service_account_namespace" {
  type        = string
  description = "Namespace for IRSA-enabled Kubernetes service accounts (used by S3 and RDS)"
  default     = "onyx"
}

variable "irsa_service_account_name" {
  type        = string
  description = "Name of the IRSA-enabled Kubernetes service account for workload access (S3 + optional RDS)"
  default     = "onyx-workload-access"
}

variable "irsa_additional_service_account_names" {
  type        = list(string)
  description = "Additional service accounts in irsa_service_account_namespace that may assume the workload IRSA role. Use this for chart-created workloads, such as <release>-sandbox-proxy, that also need RDS IAM auth. The role is created when s3_bucket_names is non-empty or RDS IAM auth is enabled."
  default     = []
}

variable "enable_rds_iam_for_service_account" {
  type        = bool
  description = "Whether to create a dedicated RDS IRSA role and service account (grants rds-db:connect)"
  default     = false
}

variable "rds_db_username" {
  type        = string
  description = "Database username to allow via rds-db:connect"
  default     = null
}

variable "rds_db_connect_arn" {
  type        = string
  description = "Full rds-db:connect ARN to allow (required when enable_rds_iam_for_service_account is true)"
  default     = null
}

variable "cluster_enabled_log_types" {
  type        = list(string)
  description = "EKS control plane log types to enable (valid: api, audit, authenticator, controllerManager, scheduler)"
  default     = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  validation {
    condition     = alltrue([for t in var.cluster_enabled_log_types : contains(["api", "audit", "authenticator", "controllerManager", "scheduler"], t)])
    error_message = "Each entry must be one of: api, audit, authenticator, controllerManager, scheduler."
  }
}

variable "cloudwatch_log_group_retention_in_days" {
  type        = number
  description = "Number of days to retain EKS control plane logs in CloudWatch (0 = never expire). Default 400 = 12 months + 30-day buffer for the common twelve-month log-retention control."
  default     = 400

  validation {
    condition     = contains([0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.cloudwatch_log_group_retention_in_days)
    error_message = "Must be a valid CloudWatch retention value (0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653)."
  }
}

variable "enable_network_policy" {
  type        = bool
  description = "Adopt the VPC CNI addon and turn on NetworkPolicy enforcement. Updates use resolve_conflicts_on_update = PRESERVE so out-of-band aws-node settings survive; the trade-off is that a cluster whose addon already sets enableNetworkPolicy=false explicitly keeps that value, and enforcement stays off. Check the addon's configuration_values after the first apply."
  default     = false
}

variable "vpc_cni_addon_version" {
  type        = string
  description = "VPC CNI addon version to pin when enable_network_policy is true. Set to the cluster's currently-running version (set CLUSTER_NAME, then: aws eks describe-addon --cluster-name \"$CLUSTER_NAME\" --addon-name vpc-cni --query 'addon.addonVersion') to avoid an unintended CNI upgrade on adoption."
  default     = "v1.20.4-eksbuild.2"
}
