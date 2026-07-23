# Onyx AWS modules

## Overview
This directory contains Terraform modules to provision the core AWS infrastructure for Onyx:

- `vpc`: Creates a VPC with public/private subnets sized for EKS
- `eks`: Provisions an Amazon EKS cluster, essential addons (EBS CSI, metrics server, cluster autoscaler), and optional IRSA for S3 access
- `postgres`: Creates an Amazon RDS for PostgreSQL instance and returns a connection URL
- `redis`: Creates an ElastiCache for Redis replication group
- `s3`: Creates an S3 bucket and locks access to a provided S3 VPC endpoint
- `opensearch`: Creates an Amazon OpenSearch domain for managed search workloads
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

## T-shirt sizing
The `onyx` module takes a `size` input (`small` | `medium` | `large`, default `medium`) that sets
coherent defaults for every compute and data-plane knob. Pick a tier from your expected scale:

| Tier | Users | Documents |
|---|---|---|
| `small` | up to ~200 | < ~500k |
| `medium` | ~200–1,000 | ~0.5–2M |
| `large` | 1,000+ | multi-million |

What each tier provisions:

| Setting | small | medium | large |
|---|---|---|---|
| Main EKS node group | m7i.4xlarge ×1–3 | m7i.4xlarge ×1–5 | m7i.4xlarge ×2–8 |
| Document-index node¹ | m6i.xlarge, 100 GB | m6i.2xlarge, 100 GB | r6i.4xlarge, 512 GB |
| RDS Postgres | db.t4g.large, 64→256 GB | db.t4g.large, 128→512 GB | db.m7g.xlarge, 256→1024 GB |
| ElastiCache Redis | cache.m6g.large | cache.m6g.xlarge | cache.m6g.2xlarge |
| OpenSearch data² | r7g.large ×1, 256 GB | r8g.xlarge ×1, 512 GB | r8g.2xlarge ×1, 1 TB (12k IOPS) |
| OpenSearch masters² | 3× m7g.medium | 3× m7g.medium | 3× m7g.medium |

¹ The dedicated index node group only matters when running the document index in-cluster
(the Helm chart's OpenSearch StatefulSet). If you use a managed OpenSearch domain instead
(`enable_opensearch = true`), the index node sits idle — consider overriding
`vespa_node_instance_types` to a small instance.
² Only created when `enable_opensearch = true`. All tiers default to a single data node
without zone awareness; RDS is likewise single-AZ. For HA, set
`opensearch_instance_count = 3`, `opensearch_zone_awareness_enabled = true` (and optionally
`opensearch_multi_az_with_standby_enabled = true`).

These defaults are calibrated from Onyx's own managed production fleet: memory, not CPU, is
the binding dimension on the Kubernetes side, and the burstable `db.t4g.large` holds up to
roughly the medium tier before CPU peaks make a fixed-performance class worthwhile.

Every value in the table is just a default — any sizing variable set to a non-null value
(e.g. `postgres_instance_type`, `opensearch_instance_type`, `main_node_max_size`) overrides
its tier.

**Upgrading from a pre-sizing version of these modules:** the previous hardcoded defaults
were `db.t4g.large` with 20 GB gp2 and no storage autoscaling, `cache.m6g.xlarge`, and a
3×r8g.large multi-AZ OpenSearch domain. The default `medium` tier keeps the same EKS node
groups and Redis node type, grows Postgres storage online (gp2→gp3 conversion is also
online; storage can never shrink), and — if you enabled OpenSearch and relied on the old
defaults — would replace the domain with a single-node shape, so pin the old values
explicitly before applying if you want to keep them.

### Using an existing VPC
If you already have a VPC and subnets, disable VPC creation and provide IDs, CIDR, and the ID of the existing S3 gateway endpoint in that VPC:

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
  s3_vpc_endpoint_id = "vpce-xxxxxxxxxxxxxxxxx"
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
- `size` (`small`/`medium`/`large`, default `medium`) — see "T-shirt sizing" above — plus per-setting overrides (`main_node_*`, `vespa_node_*`, `postgres_instance_type`, `postgres_storage_gb`, `redis_instance_type`, `opensearch_*`)
- `postgres_username`, `postgres_password`
- `create_vpc` (default true) or existing VPC details and `s3_vpc_endpoint_id`
- WAF controls such as `waf_allowed_ip_cidrs`, `waf_common_rule_set_count_rules`, rate limits, geo restrictions, and logging retention
- Optional OpenSearch controls such as `enable_opensearch`, sizing, credentials, and log retention

### `vpc`
- Builds a VPC sized for EKS with multiple private and public subnets
- Outputs: `vpc_id`, `private_subnets`, `public_subnets`, `vpc_cidr_block`, `s3_vpc_endpoint_id`

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
- Creates an S3 bucket for file storage and scopes access to the provided S3 gateway VPC endpoint

### `opensearch`
- Creates an Amazon OpenSearch domain inside the VPC
- Supports custom subnets, security groups, fine-grained access control, encryption, and CloudWatch log publishing
- Outputs domain endpoints, ARN, and the managed security group ID when it creates one

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
