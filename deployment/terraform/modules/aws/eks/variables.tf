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
  default     = false
}

variable "cluster_endpoint_public_access_cidrs" {
  type        = list(string)
  description = "List of CIDR blocks allowed to access the public EKS API endpoint"
  default     = []
}

variable "eks_managed_node_groups" {
  type        = map(any)
  description = "EKS managed node groups with EBS volume configuration"
  default = {
    # Main node group for all pods except Vespa
    main = {
      name           = "main-node-group"
      instance_types = ["r7i.4xlarge"]
      min_size       = 1
      max_size       = 5
      # EBS volume configuration
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 50
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
      instance_types = ["m6i.2xlarge"]
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
