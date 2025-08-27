# Onyx AWS modules

## Overview
This directory contains Terraform modules to provision the core AWS infrastructure for Onyx:

- `vpc`: Creates a VPC with public/private subnets sized for EKS
- `eks`: Provisions an Amazon EKS cluster, essential addons (EBS CSI, metrics server, cluster autoscaler), and optional IRSA for S3 access
- `postgres`: Creates an Amazon RDS for PostgreSQL instance and returns a connection URL
- `redis`: Creates an ElastiCache for Redis replication group
- `s3`: Creates an S3 bucket (and VPC endpoint) for file storage
- `onyx`: A higher-level composition that wires the above modules together for a complete, opinionated stack

Use the `onyx` module if you want a working EKS + Postgres + Redis + S3 stack with sane defaults. Use the individual modules if you need more granular control.

## Quickstart (copy/paste)
The snippet below shows a minimal working example that:
- Sets up providers
- Waits for EKS to be ready
- Configures `kubernetes` and `helm` providers against the created cluster
- Provisions the full Onyx AWS stack via the `onyx` module

```hcl
locals {
  region = "us-west-2"
}

provider "aws" {
  region = local.region
}

module "onyx" {
  # If your root module is next to this modules/ directory:
  # source = "./modules/aws/onyx"
  # If referencing from this repo as a template, adjust the path accordingly.
  source = "./modules/aws/onyx"

  region            = local.region
  name              = "onyx"            # used as a prefix and workspace-aware
  postgres_username = "pgusername"
  postgres_password = "your-postgres-password"
  # create_vpc    = true  # default true; set to false to use an existing VPC (see below)
}

resource "null_resource" "wait_for_cluster" {
  provisioner "local-exec" {
    command = "aws eks wait cluster-active --name ${module.onyx.cluster_name} --region ${local.region}"
  }
}

data "aws_eks_cluster" "eks" {
  name       = module.onyx.cluster_name
  depends_on = [null_resource.wait_for_cluster]
}

data "aws_eks_cluster_auth" "eks" {
  name       = module.onyx.cluster_name
  depends_on = [null_resource.wait_for_cluster]
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.eks.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.eks.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.eks.token
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.eks.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.eks.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.eks.token
  }
}

# Optional: expose handy outputs at the root module level
output "cluster_name" {
  value = module.onyx.cluster_name
}
output "postgres_connection_url" {
  value     = module.onyx.postgres_connection_url
  sensitive = true
}
output "redis_connection_url" {
  value     = module.onyx.redis_connection_url
  sensitive = true
}
```

Apply with:

```bash
terraform init
terraform apply
```

### Using an existing VPC
If you already have a VPC and subnets, disable VPC creation and provide IDs and CIDR:

```hcl
module "onyx" {
  source = "./modules/aws/onyx"

  region            = local.region
  name              = "onyx"
  postgres_username = "pgusername"
  postgres_password = "your-postgres-password"

  create_vpc       = false
  vpc_id           = "vpc-xxxxxxxx"
  private_subnets  = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
  public_subnets   = ["subnet-dddd", "subnet-eeee", "subnet-ffff"]
  vpc_cidr_block   = "10.0.0.0/16"
}
```

## What each module does

### `onyx`
- Orchestrates `vpc`, `eks`, `postgres`, `redis`, and `s3`
- Names resources using `name` and the current Terraform workspace
- Exposes convenient outputs:
  - `cluster_name`: EKS cluster name
  - `postgres_connection_url` (sensitive): `postgres://...`
  - `redis_connection_url` (sensitive): hostname:port

Inputs (common):
- `name` (default `onyx`), `region` (default `us-west-2`), `tags`
- `postgres_username`, `postgres_password`
- `create_vpc` (default true) or existing VPC details

### `vpc`
- Builds a VPC sized for EKS with multiple private and public subnets
- Outputs: `vpc_id`, `private_subnets`, `public_subnets`, `vpc_cidr_block`

### `eks`
- Creates the EKS cluster and node groups
- Enables addons: EBS CSI driver, metrics server, cluster autoscaler
- Optionally configures IRSA for S3 access to specified buckets
- Outputs: `cluster_name`, `cluster_endpoint`, `cluster_certificate_authority_data`, `s3_access_role_arn` (if created)

Key inputs include:
- `cluster_name`, `cluster_version` (default `1.33`)
- `vpc_id`, `subnet_ids`
- `public_cluster_enabled` (default true), `private_cluster_enabled` (default false)
- `cluster_endpoint_public_access_cidrs` (optional)
- `eks_managed_node_groups` (defaults include a main and a vespa-dedicated group with GP3 volumes)
- `s3_bucket_names` (optional list). If set, creates an IRSA role and Kubernetes service account for S3 access

### `postgres`
- Amazon RDS for PostgreSQL with parameterized instance size, storage, version
- Accepts VPC/subnets and ingress CIDRs; returns a ready-to-use connection URL

### `redis`
- ElastiCache for Redis (transit encryption enabled by default)
- Supports optional `auth_token` and instance sizing
- Outputs endpoint, port, and whether SSL is enabled

### `s3`
- Creates an S3 bucket for file storage and a gateway VPC endpoint for private access

## Installing the Onyx Helm chart (after Terraform)
Once the cluster is active, deploy application workloads via Helm. You can use the chart in `deployment/helm/charts/onyx`.

```bash
# Set kubeconfig to your new cluster (if you’re not using the TF providers for kubernetes/helm)
aws eks update-kubeconfig --name $(terraform output -raw cluster_name) --region ${AWS_REGION:-us-west-2}

kubectl create namespace onyx --dry-run=client -o yaml | kubectl apply -f -

# If using AWS S3 via IRSA created by the EKS module, consider disabling MinIO
# Replace the path below with the absolute or correct relative path to the onyx Helm chart
helm upgrade --install onyx /path/to/onyx/deployment/helm/charts/onyx \
  --namespace onyx \
  --set minio.enabled=false \
  --set serviceAccount.create=false \
  --set serviceAccount.name=onyx-s3-access
```

Notes:
- The EKS module can create an IRSA role plus a Kubernetes `ServiceAccount` named `onyx-s3-access` (by default in namespace `onyx`) when `s3_bucket_names` is provided. Use that service account in the Helm chart to avoid static S3 credentials.
- If you prefer MinIO inside the cluster, leave `minio.enabled=true` (default) and skip IRSA.

## Workflow tips
- First apply can be infra-only; once EKS is active, install the Helm chart.
- Use Terraform workspaces to create isolated environments; the `onyx` module automatically includes the workspace in resource names.

## Security
- Database and Redis connection outputs are marked sensitive. Handle them carefully.
- When using IRSA, avoid storing long-lived S3 credentials in secrets.
