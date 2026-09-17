# The Craft sandbox node group's map key was `craft_sandbox`; it is now
# `sandbox`. The key is part of the upstream module's instance address, so
# without this the group is destroyed and recreated, evicting its workloads.
moved {
  from = module.eks.module.eks_managed_node_group["craft_sandbox"]
  to   = module.eks.module.eks_managed_node_group["sandbox"]
}

locals {
  s3_bucket_arns = [for name in var.s3_bucket_names : {
    bucket_arn     = "arn:aws:s3:::${name}"
    bucket_objects = "arn:aws:s3:::${name}/*"
  }]

  workload_irsa_enabled = (
    length(var.s3_bucket_names) > 0 ||
    (var.enable_rds_iam_for_service_account && var.rds_db_connect_arn != null)
  )

  workload_irsa_service_account_subjects = [
    for service_account_name in distinct(concat(
      [var.irsa_service_account_name],
      var.irsa_additional_service_account_names,
    )) :
    "system:serviceaccount:${var.irsa_service_account_namespace}:${service_account_name}"
  ]

  # Optional dedicated GPU node group for the embedding model server.
  # Tainted so ONLY pods that tolerate nvidia.com/gpu (the model pod) land here,
  # and uses the EKS NVIDIA accelerated AMI which ships the GPU driver + runtime.
  gpu_node_groups = var.enable_gpu_node ? {
    gpu = {
      name           = "gpu-node-group"
      instance_types = var.gpu_node_instance_types
      ami_type       = "AL2023_x86_64_NVIDIA"
      min_size       = 1
      max_size       = 1
      labels = {
        "onyx.app/gpu" = "true"
      }
      taints = [
        {
          key    = "nvidia.com/gpu"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
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
    }
  } : {}

  # Optional dedicated Craft sandbox node group. Sandbox pods pin here
  # via nodeSelector onyx.app/workload=sandbox + toleration of the workload taint.
  # IMDSv2 hop-limit 1 blocks sandboxed containers from the node metadata service.
  # The root disk is sized via craft_sandbox_node_disk_size_gb so ephemeral-storage
  # stops being the binding scheduling dimension (each sandbox pod reserves ~5.5Gi
  # eph; the AMI default ~20Gi caps a node at ~3 sandboxes vs ~7 by CPU).
  craft_sandbox_node_groups = var.enable_craft ? {
    sandbox = {
      name           = "sandbox-node-group"
      instance_types = var.craft_sandbox_node_instance_types
      min_size       = var.craft_sandbox_node_min_size
      max_size       = var.craft_sandbox_node_max_size
      desired_size   = var.craft_sandbox_node_desired_size
      labels = {
        "onyx.app/workload" = "sandbox"
      }
      taints = [
        {
          key    = "workload"
          value  = "sandbox"
          effect = "NO_SCHEDULE"
        }
      ]
      metadata_options = {
        http_endpoint               = "enabled"
        http_tokens                 = "required"
        http_put_response_hop_limit = 1
      }
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = var.craft_sandbox_node_disk_size_gb
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
            iops                  = 3000
            throughput            = 125
          }
        }
      }
      # cluster-autoscaler auto-discovery: tag the node group's ASG so demand
      # beyond min_size adds nodes (and scales back down when idle).
      tags = {
        "k8s.io/cluster-autoscaler/enabled"             = "true"
        "k8s.io/cluster-autoscaler/${var.cluster_name}" = "owned"
      }
    }
  } : {}
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id                                   = var.vpc_id
  subnet_ids                               = var.subnet_ids
  cluster_endpoint_public_access           = var.public_cluster_enabled
  cluster_endpoint_private_access          = var.private_cluster_enabled
  cluster_endpoint_public_access_cidrs     = var.cluster_endpoint_public_access_cidrs
  enable_cluster_creator_admin_permissions = true

  # Control plane logging
  cluster_enabled_log_types              = var.cluster_enabled_log_types
  cloudwatch_log_group_retention_in_days = var.cloudwatch_log_group_retention_in_days

  # Opt-in per cluster: adopts the VPC CNI addon and turns on NetworkPolicy
  # enforcement. Off by default so existing clusters' NetworkPolicies stay
  # inert (the cloud cluster has legacy policies of unknown effect).
  cluster_addons = var.enable_network_policy ? {
    vpc-cni = {
      # Pin to the cluster's running CNI so adoption only flips enableNetworkPolicy.
      addon_version = var.vpc_cni_addon_version
      # PRESERVE keeps out-of-band aws-node settings; OVERWRITE on create is
      # required to adopt the previously-unmanaged addon (PRESERVE isn't valid there).
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "PRESERVE"
      configuration_values = jsonencode({
        enableNetworkPolicy = "true"
      })
    }
  } : {}

  eks_managed_node_group_defaults = {
    ami_type = "AL2023_x86_64_STANDARD"
  }

  eks_managed_node_groups = {
    for k, v in merge(var.eks_managed_node_groups, local.gpu_node_groups, local.craft_sandbox_node_groups) : k => merge(v,
      {
        instance_types = v.instance_types != null ? v.instance_types : (
          k == "main" ? var.main_node_instance_types :
          k == "vespa" ? var.vespa_node_instance_types :
          v.instance_types
        )
      },
      # Only add subnet_ids override for vespa node group if specified
      k == "vespa" && length(var.vespa_node_subnet_ids) > 0 ? {
        subnet_ids = var.vespa_node_subnet_ids
      } : {},
      # Only add subnet_ids override for main node group if specified
      k == "main" && length(var.main_node_subnet_ids) > 0 ? {
        subnet_ids = var.main_node_subnet_ids
      } : {},
      # Override main node group scaling bounds (defaults preserve prior behavior).
      # Raising min_size forces the cluster-autoscaler to keep an always-on
      # baseline. desired_size must be >= min_size or the EKS API rejects the
      # node group at creation (the upstream module defaults desired to 1 and
      # ignores changes to it after create).
      k == "main" ? {
        min_size     = coalesce(var.main_node_min_size, v.min_size)
        max_size     = coalesce(var.main_node_max_size, v.max_size)
        desired_size = try(v.desired_size, coalesce(var.main_node_min_size, v.min_size))
      } : {},
      # Disk override for the Vespa/document-index node; null keeps the map
      # default. Merge preserves any other device mappings on the group.
      k == "vespa" && var.vespa_node_disk_size_gb != null ? {
        block_device_mappings = merge(try(v.block_device_mappings, {}), {
          xvda = {
            device_name = "/dev/xvda"
            ebs = merge(
              try(v.block_device_mappings.xvda.ebs, {}),
              { volume_size = var.vespa_node_disk_size_gb }
            )
          }
        })
      } : {}
    ) if k != "vespa" || var.vespa_node_enabled
  }

  tags = var.tags
}

# NVIDIA device plugin: advertises nvidia.com/gpu on the GPU nodes so the
# embedding model pod can request it. Tolerates the GPU taint and only runs on
# nodes labeled onyx.app/gpu=true. Only created when the GPU node group exists.
resource "helm_release" "nvidia_device_plugin" {
  count = var.enable_gpu_node ? 1 : 0

  name       = "nvidia-device-plugin"
  repository = "https://nvidia.github.io/k8s-device-plugin"
  chart      = "nvidia-device-plugin"
  version    = "0.17.1"
  namespace  = "kube-system"

  # Null out the chart's default Node Feature Discovery affinity (we don't run
  # NFD, so its pci-10de / nvidia.com/gpu.present requirements exclude our node).
  # null (not {}) is required to actually override the chart default. Pin the
  # plugin to our labeled, tainted GPU node via nodeSelector + toleration.
  values = [<<-YAML
    affinity: null
    nodeSelector:
      onyx.app/gpu: "true"
    tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
  YAML
  ]

  depends_on = [module.eks]
}

# https://aws.amazon.com/blogs/containers/amazon-ebs-csi-driver-is-now-generally-available-in-amazon-eks-add-ons/
data "aws_iam_policy" "ebs_csi_policy" {
  arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

module "irsa-ebs-csi" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc"
  version = "4.7.0"

  create_role                   = true
  role_name                     = "AmazonEKSTFEBSCSIRole-${module.eks.cluster_name}"
  provider_url                  = module.eks.oidc_provider
  role_policy_arns              = [data.aws_iam_policy.ebs_csi_policy.arn]
  oidc_fully_qualified_subjects = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]

  depends_on = [module.eks]
}

# Create the EBS CSI Driver addon for volume provisioning.
resource "aws_eks_addon" "ebs-csi" {
  cluster_name             = module.eks.cluster_name
  addon_name               = "aws-ebs-csi-driver"
  service_account_role_arn = module.irsa-ebs-csi.iam_role_arn
  tags                     = var.tags

  depends_on = [module.eks]
}

# Create GP3 storage class for EBS volumes
resource "kubernetes_storage_class" "gp3_default" {
  count = var.create_gp3_storage_class ? 1 : 0
  metadata {
    name = "gp3"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "true"
    }
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type = "gp3"
  }

  depends_on = [aws_eks_addon.ebs-csi]
}

# Create some important addons for the EKS cluster.
module "eks_blueprints_addons" {
  source  = "aws-ia/eks-blueprints-addons/aws"
  version = "1.16.3"

  cluster_name      = module.eks.cluster_name
  cluster_endpoint  = module.eks.cluster_endpoint
  cluster_version   = module.eks.cluster_version
  oidc_provider_arn = module.eks.oidc_provider_arn

  enable_aws_load_balancer_controller = true
  enable_karpenter                    = false
  enable_metrics_server               = true
  enable_cluster_autoscaler           = true

  depends_on = [module.eks]
}

# Supplementary RBAC for the cluster-autoscaler: its chart's hardcoded
# ClusterRole covers storageclasses/csinodes/csidrivers but NOT
# volumeattachments (and exposes no values hook to extend it), so EBS-AZ-aware
# scale-up fails with "cannot list volumeattachments" — a pod pending on an
# AZ-locked volume never triggers a node in that AZ. NOTE: if these objects
# were already created by hand on the cluster, import them before the first
# apply:
#   terraform import '...kubernetes_cluster_role.cluster_autoscaler_volumeattachments' onyx-cluster-autoscaler-volumeattachments
#   terraform import '...kubernetes_cluster_role_binding.cluster_autoscaler_volumeattachments' onyx-cluster-autoscaler-volumeattachments
resource "kubernetes_cluster_role" "cluster_autoscaler_volumeattachments" {
  metadata {
    name   = "onyx-cluster-autoscaler-volumeattachments"
    labels = { "app.kubernetes.io/managed-by" = "onyx-infra" }
  }

  rule {
    api_groups = ["storage.k8s.io"]
    resources  = ["volumeattachments"]
    verbs      = ["list", "watch", "get"]
  }

  depends_on = [module.eks_blueprints_addons]
}

resource "kubernetes_cluster_role_binding" "cluster_autoscaler_volumeattachments" {
  metadata {
    name   = "onyx-cluster-autoscaler-volumeattachments"
    labels = { "app.kubernetes.io/managed-by" = "onyx-infra" }
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.cluster_autoscaler_volumeattachments.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = "cluster-autoscaler-sa"
    namespace = "kube-system"
  }

  depends_on = [module.eks_blueprints_addons]
}

# Create IAM policy for S3 access (optional)
resource "aws_iam_policy" "s3_access_policy" {
  count       = length(var.s3_bucket_names) == 0 ? 0 : 1
  name        = "${module.eks.cluster_name}-s3-access-policy"
  description = "Policy for S3 access from EKS cluster"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = flatten([
          for a in local.s3_bucket_arns : [a.bucket_arn, a.bucket_objects]
        ])
      }
    ]
  })
}

# Create IAM role for workload access using IRSA (S3 + RDS)
module "irsa-workload-access" {
  count   = local.workload_irsa_enabled ? 1 : 0
  source  = "terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc"
  version = "4.7.0"

  create_role                   = true
  role_name                     = "AmazonEKSTFWorkloadAccessRole-${module.eks.cluster_name}"
  provider_url                  = module.eks.oidc_provider
  role_policy_arns              = aws_iam_policy.s3_access_policy[*].arn
  oidc_fully_qualified_subjects = local.workload_irsa_service_account_subjects

  depends_on = [module.eks]
}

# Create Kubernetes service account for workload IRSA access (optional)
resource "kubernetes_service_account" "s3_access" {
  count = local.workload_irsa_enabled ? 1 : 0
  metadata {
    name      = var.irsa_service_account_name
    namespace = var.irsa_service_account_namespace
    annotations = {
      "eks.amazonaws.com/role-arn" = module.irsa-workload-access[0].iam_role_arn
    }
  }
}

# If RDS IAM auth is enabled, create a policy to allow the workload IRSA role to connect to RDS using IAM auth
resource "aws_iam_policy" "rds_iam_connect_policy" {
  count       = var.enable_rds_iam_for_service_account && var.rds_db_connect_arn != null ? 1 : 0
  name        = "${module.eks.cluster_name}-rds-iam-connect-policy"
  description = "Allow EKS service account to connect to RDS using IAM auth"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "rds-db:connect"
        ],
        Resource = [
          var.rds_db_connect_arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "attach_rds_connect_to_workload_role" {
  count      = var.enable_rds_iam_for_service_account && var.rds_db_connect_arn != null ? 1 : 0
  role       = module.irsa-workload-access[0].iam_role_name
  policy_arn = aws_iam_policy.rds_iam_connect_policy[0].arn

  depends_on = [module.irsa-workload-access]
}
