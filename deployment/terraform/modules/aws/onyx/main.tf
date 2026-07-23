locals {
  workspace       = terraform.workspace
  name            = var.name
  merged_tags     = merge(var.tags, { tenant = local.name, environment = local.workspace })
  vpc_name        = "${var.name}-vpc-${local.workspace}"
  cluster_name    = "${var.name}-${local.workspace}"
  bucket_name     = "${var.name}-file-store-${local.workspace}"
  redis_name      = "${var.name}-redis-${local.workspace}"
  postgres_name   = "${var.name}-postgres-${local.workspace}"
  opensearch_name = var.opensearch_domain_name != null ? var.opensearch_domain_name : "${var.name}-opensearch-${local.workspace}"

  vpc_id          = var.create_vpc ? module.vpc[0].vpc_id : var.vpc_id
  private_subnets = var.create_vpc ? module.vpc[0].private_subnets : var.private_subnets
  public_subnets  = var.create_vpc ? module.vpc[0].public_subnets : var.public_subnets
  vpc_cidr_block  = var.create_vpc ? module.vpc[0].vpc_cidr_block : var.vpc_cidr_block

  # T-shirt size defaults. Calibrated against the Onyx-managed production
  # fleet (Jul 2026): memory, not CPU, is the binding dimension on the EKS
  # side; the burstable db.t4g.large sustains fleet load until ~1k users but
  # peaks past 70% CPU on the largest deployments, and every production
  # OpenSearch domain runs 1 data node + 3 m7g.medium masters. Each value can
  # be overridden individually via the matching variable.
  size_defaults = {
    small = {
      main_node_instance_types                 = ["m7i.4xlarge"]
      main_node_min_size                       = 1
      main_node_max_size                       = 3
      vespa_node_instance_types                = ["m6i.xlarge"]
      vespa_node_disk_size_gb                  = 100
      postgres_instance_type                   = "db.t4g.large"
      postgres_storage_gb                      = 64
      postgres_max_storage_gb                  = 256
      redis_instance_type                      = "cache.m6g.large"
      opensearch_instance_type                 = "r7g.large.search"
      opensearch_instance_count                = 1
      opensearch_dedicated_master_type         = "m7g.medium.search"
      opensearch_multi_az_with_standby_enabled = false
      opensearch_zone_awareness_enabled        = false
      opensearch_ebs_volume_size               = 256
      opensearch_ebs_iops                      = 3000
      opensearch_ebs_throughput                = 256
    }
    medium = {
      main_node_instance_types                 = ["m7i.4xlarge"]
      main_node_min_size                       = 1
      main_node_max_size                       = 5
      vespa_node_instance_types                = ["m6i.2xlarge"]
      vespa_node_disk_size_gb                  = 100
      postgres_instance_type                   = "db.t4g.large"
      postgres_storage_gb                      = 128
      postgres_max_storage_gb                  = 512
      redis_instance_type                      = "cache.m6g.xlarge"
      opensearch_instance_type                 = "r8g.xlarge.search"
      opensearch_instance_count                = 1
      opensearch_dedicated_master_type         = "m7g.medium.search"
      opensearch_multi_az_with_standby_enabled = false
      opensearch_zone_awareness_enabled        = false
      opensearch_ebs_volume_size               = 512
      opensearch_ebs_iops                      = 3000
      opensearch_ebs_throughput                = 256
    }
    large = {
      main_node_instance_types                 = ["m7i.4xlarge"]
      main_node_min_size                       = 2
      main_node_max_size                       = 8
      vespa_node_instance_types                = ["r6i.4xlarge"]
      vespa_node_disk_size_gb                  = 512
      postgres_instance_type                   = "db.m7g.xlarge"
      postgres_storage_gb                      = 256
      postgres_max_storage_gb                  = 1024
      redis_instance_type                      = "cache.m6g.2xlarge"
      opensearch_instance_type                 = "r8g.2xlarge.search"
      opensearch_instance_count                = 1
      opensearch_dedicated_master_type         = "m7g.medium.search"
      opensearch_multi_az_with_standby_enabled = false
      opensearch_zone_awareness_enabled        = false
      opensearch_ebs_volume_size               = 1024
      opensearch_ebs_iops                      = 12000
      opensearch_ebs_throughput                = 1024
    }
  }
  sizing = local.size_defaults[var.size]

  # Explicit per-setting overrides win over the tier defaults.
  main_node_instance_types  = var.main_node_instance_types != null ? var.main_node_instance_types : local.sizing.main_node_instance_types
  main_node_min_size        = coalesce(var.main_node_min_size, local.sizing.main_node_min_size)
  main_node_max_size        = coalesce(var.main_node_max_size, local.sizing.main_node_max_size)
  vespa_node_instance_types = var.vespa_node_instance_types != null ? var.vespa_node_instance_types : local.sizing.vespa_node_instance_types
  vespa_node_disk_size_gb   = coalesce(var.vespa_node_disk_size_gb, local.sizing.vespa_node_disk_size_gb)
  postgres_instance_type    = coalesce(var.postgres_instance_type, local.sizing.postgres_instance_type)
  postgres_storage_gb       = coalesce(var.postgres_storage_gb, local.sizing.postgres_storage_gb)
  postgres_max_storage_gb   = coalesce(var.postgres_max_storage_gb, local.sizing.postgres_max_storage_gb)
  redis_instance_type       = coalesce(var.redis_instance_type, local.sizing.redis_instance_type)

  opensearch_instance_type                 = coalesce(var.opensearch_instance_type, local.sizing.opensearch_instance_type)
  opensearch_instance_count                = coalesce(var.opensearch_instance_count, local.sizing.opensearch_instance_count)
  opensearch_dedicated_master_type         = coalesce(var.opensearch_dedicated_master_type, local.sizing.opensearch_dedicated_master_type)
  opensearch_multi_az_with_standby_enabled = coalesce(var.opensearch_multi_az_with_standby_enabled, local.sizing.opensearch_multi_az_with_standby_enabled)
  opensearch_zone_awareness_enabled        = coalesce(var.opensearch_zone_awareness_enabled, local.sizing.opensearch_zone_awareness_enabled)
  opensearch_ebs_volume_size               = coalesce(var.opensearch_ebs_volume_size, local.sizing.opensearch_ebs_volume_size)
  opensearch_ebs_iops                      = coalesce(var.opensearch_ebs_iops, local.sizing.opensearch_ebs_iops)
  opensearch_ebs_throughput                = coalesce(var.opensearch_ebs_throughput, local.sizing.opensearch_ebs_throughput)

  # A domain's subnet count must match its AZ spread: 1 subnet without zone
  # awareness (single-data-node tiers), 3 with it.
  opensearch_subnet_ids = length(var.opensearch_subnet_ids) > 0 ? var.opensearch_subnet_ids : (
    local.opensearch_zone_awareness_enabled ? slice(local.private_subnets, 0, 3) : slice(local.private_subnets, 0, 1)
  )
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.merged_tags
  }
}

module "vpc" {
  source = "../vpc"

  count    = var.create_vpc ? 1 : 0
  vpc_name = local.vpc_name
  tags     = local.merged_tags
}

module "redis" {
  source        = "../redis"
  name          = local.redis_name
  vpc_id        = local.vpc_id
  subnet_ids    = local.private_subnets
  instance_type = local.redis_instance_type
  ingress_cidrs = [local.vpc_cidr_block]
  tags          = local.merged_tags

  # Pass Redis authentication token as a sensitive input variable
  auth_token = var.redis_auth_token
}

module "postgres" {
  source        = "../postgres"
  identifier    = local.postgres_name
  vpc_id        = local.vpc_id
  subnet_ids    = local.private_subnets
  ingress_cidrs = [local.vpc_cidr_block]

  instance_type  = local.postgres_instance_type
  storage_gb     = local.postgres_storage_gb
  max_storage_gb = local.postgres_max_storage_gb

  username            = var.postgres_username
  password            = var.postgres_password
  tags                = local.merged_tags
  enable_rds_iam_auth = var.enable_iam_auth

  backup_retention_period = var.postgres_backup_retention_period
  backup_window           = var.postgres_backup_window
}

module "s3" {
  source             = "../s3"
  bucket_name        = local.bucket_name
  tags               = local.merged_tags
  s3_vpc_endpoint_id = var.create_vpc ? module.vpc[0].s3_vpc_endpoint_id : var.s3_vpc_endpoint_id
}

module "eks" {
  source          = "../eks"
  cluster_name    = local.cluster_name
  vpc_id          = local.vpc_id
  subnet_ids      = concat(local.private_subnets, local.public_subnets)
  tags            = local.merged_tags
  s3_bucket_names = [local.bucket_name]

  main_node_instance_types  = local.main_node_instance_types
  main_node_min_size        = local.main_node_min_size
  main_node_max_size        = local.main_node_max_size
  vespa_node_instance_types = local.vespa_node_instance_types
  vespa_node_disk_size_gb   = local.vespa_node_disk_size_gb

  irsa_additional_service_account_names = var.irsa_additional_service_account_names

  enable_craft                      = var.enable_craft
  craft_sandbox_node_instance_types = var.craft_sandbox_node_instance_types
  craft_sandbox_node_min_size       = var.craft_sandbox_node_min_size
  craft_sandbox_node_max_size       = var.craft_sandbox_node_max_size
  craft_sandbox_node_desired_size   = var.craft_sandbox_node_desired_size
  craft_sandbox_node_disk_size_gb   = var.craft_sandbox_node_disk_size_gb

  main_node_subnet_ids = length(var.main_node_subnet_ids) > 0 ? var.main_node_subnet_ids : (
    var.main_node_private_subnets_only ? local.private_subnets : []
  )

  # Wire RDS IAM connection for the same IRSA service account used by apps
  enable_rds_iam_for_service_account = var.enable_iam_auth
  rds_db_username                    = var.postgres_username
  rds_db_connect_arn                 = var.rds_db_connect_arn

  # These variables must be defined in variables.tf or passed in via parent module
  public_cluster_enabled               = var.public_cluster_enabled
  private_cluster_enabled              = var.private_cluster_enabled
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs

  # Control plane logging
  cluster_enabled_log_types              = var.eks_cluster_enabled_log_types
  cloudwatch_log_group_retention_in_days = var.eks_cloudwatch_log_group_retention_in_days
}

module "waf" {
  source = "../waf"

  name = local.name
  tags = local.merged_tags

  # WAF configuration with sensible defaults
  allowed_ip_cidrs                      = var.waf_allowed_ip_cidrs
  common_rule_set_count_rules           = var.waf_common_rule_set_count_rules
  rate_limit_requests_per_5_minutes     = var.waf_rate_limit_requests_per_5_minutes
  api_rate_limit_requests_per_5_minutes = var.waf_api_rate_limit_requests_per_5_minutes
  geo_restriction_countries             = var.waf_geo_restriction_countries
  enable_logging                        = var.waf_enable_logging
  log_retention_days                    = var.waf_log_retention_days
}

module "opensearch" {
  source = "../opensearch"
  count  = var.enable_opensearch ? 1 : 0

  name   = local.opensearch_name
  vpc_id = local.vpc_id
  # Prefer setting subnet_ids explicitly if the state of private_subnets is
  # unclear.
  subnet_ids    = local.opensearch_subnet_ids
  ingress_cidrs = [local.vpc_cidr_block]
  tags          = local.merged_tags

  # Reuse EKS security groups
  security_group_ids = [module.eks.node_security_group_id, module.eks.cluster_security_group_id]

  # Configuration
  engine_version                = var.opensearch_engine_version
  instance_type                 = local.opensearch_instance_type
  instance_count                = local.opensearch_instance_count
  dedicated_master_enabled      = var.opensearch_dedicated_master_enabled
  dedicated_master_type         = local.opensearch_dedicated_master_type
  multi_az_with_standby_enabled = local.opensearch_multi_az_with_standby_enabled
  zone_awareness_enabled        = local.opensearch_zone_awareness_enabled
  ebs_volume_size               = local.opensearch_ebs_volume_size
  ebs_iops                      = local.opensearch_ebs_iops
  ebs_throughput                = local.opensearch_ebs_throughput

  # Authentication
  internal_user_database_enabled = var.opensearch_internal_user_database_enabled
  master_user_name               = var.opensearch_master_user_name
  master_user_password           = var.opensearch_master_user_password

  # Logging
  enable_logging     = var.opensearch_enable_logging
  log_retention_days = var.opensearch_log_retention_days
}
