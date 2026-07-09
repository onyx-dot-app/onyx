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

  # Optional dedicated node group for sandbox pods (nodeSelector/toleration below).
  # IMDSv2 hop-limit 1 blocks sandboxed containers from the node metadata service.
  craft_sandbox_node_groups = var.enable_craft ? {
    craft_sandbox = {
      name           = "sandbox-node-group"
      instance_types = var.craft_sandbox_node_instance_types
      min_size       = var.craft_sandbox_node_min_size
      max_size       = var.craft_sandbox_node_max_size
      desired_size   = var.craft_sandbox_node_desired_size
      # Keep the sandbox nodes on the upstream shared node security group only.
      # Attaching the EKS primary cluster SG as well puts two
      # kubernetes.io/cluster/<name>-tagged SGs on the same nodes, which breaks
      # tag-based discovery in controllers such as AWS Load Balancer Controller.
      labels = {
        "onyx.app/workload" = "sandbox"
      }
      taints = [{
        key    = "workload"
        value  = "sandbox"
        effect = "NO_SCHEDULE"
      }]
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
          }
        }
      }
      # cluster-autoscaler auto-discovery tags (inert unless cluster-autoscaler
      # runs in the cluster). min_size stays >= 1 so the group never scales to
      # zero: scaling back up from zero would also require node-template
      # label/taint tags, which are not set here.
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

  eks_managed_node_group_defaults = {
    ami_type = "AL2023_x86_64_STANDARD"
  }

  eks_managed_node_groups = merge({
    for k, v in var.eks_managed_node_groups : k => merge(v,
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
      } : {}
    )
  }, local.craft_sandbox_node_groups)

  tags = var.tags
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
