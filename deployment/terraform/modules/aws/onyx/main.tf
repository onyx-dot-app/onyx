locals {
  workspace     = terraform.workspace
  name          = var.name
  merged_tags   = merge(var.tags, { tenant = local.name, environment = local.workspace })
  vpc_name      = "${var.name}-vpc-${local.workspace}"
  cluster_name  = "${var.name}-${local.workspace}"
  bucket_name   = "${var.name}-file-store-${local.workspace}"
  redis_name    = "${var.name}-redis-${local.workspace}"
  postgres_name = "${var.name}-postgres-${local.workspace}"

  vpc_id          = var.create_vpc ? module.vpc[0].vpc_id : var.vpc_id
  private_subnets = var.create_vpc ? module.vpc[0].private_subnets : var.private_subnets
  public_subnets  = var.create_vpc ? module.vpc[0].public_subnets : var.public_subnets
  vpc_cidr_block  = var.create_vpc ? module.vpc[0].vpc_cidr_block : var.vpc_cidr_block
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
  instance_type = "cache.m6g.xlarge"
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

  username = var.postgres_username
  password = var.postgres_password
  tags     = local.merged_tags
}

module "s3" {
  source      = "../s3"
  bucket_name = local.bucket_name
  region      = var.region
  vpc_id      = local.vpc_id
  tags        = local.merged_tags
}

module "eks" {
  source          = "../eks"
  cluster_name    = local.cluster_name
  vpc_id          = local.vpc_id
  subnet_ids      = concat(local.private_subnets, local.public_subnets)
  tags            = local.merged_tags
  s3_bucket_names = [local.bucket_name]

  # These variables must be defined in variables.tf or passed in via parent module
  public_cluster_enabled  = var.public_cluster_enabled
  private_cluster_enabled = var.private_cluster_enabled
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs
}
