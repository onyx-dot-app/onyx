# Onyx AWS modules

## Overview
This directory contains Terraform modules to provision the core AWS infrastructure for Onyx:

- `vpc`: Creates a VPC with public/private subnets sized for EKS, an optional S3 gateway endpoint, and VPC flow logs
- `eks`: Provisions an Amazon EKS cluster, essential addons (EBS CSI, metrics server, cluster autoscaler), and optional IRSA for S3 and RDS access
- `postgres`: Creates an Amazon RDS for PostgreSQL instance, CloudWatch alarms, and returns a connection URL
- `redis`: Creates an ElastiCache for Redis replication group with CloudWatch alarms
- `s3`: Creates an S3 bucket with versioning, encryption, lifecycle rules, and a scoped bucket policy
- `opensearch`: Creates an Amazon OpenSearch domain for managed search workloads, with CloudWatch alarms
- `onyx`: A higher-level composition that wires the above modules together for a complete, opinionated stack

Use the `onyx` module if you want a working EKS + Postgres + Redis + S3 stack with sane defaults. Use the individual modules if you need more granular control.

These are the same modules Onyx runs for its own managed deployments. The managed
deployments add operational wiring on top (alert routing, secret management, log
aggregation) but provision the underlying AWS infrastructure from exactly this code.

## Quickstart (copy/paste)
The snippet below shows a minimal working example that:
- Sets up providers
- Waits for EKS to be ready
- Configures `kubernetes` and `helm` providers against the created cluster
- Provisions the full Onyx AWS stack via the `onyx` module

```hcl
locals {
  region            = "us-west-2"
  postgres_username = "pgusername"
  # Supply this from a secret store or TF_VAR_ in anything but a scratch stack.
  postgres_password = "your-postgres-password"
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
  postgres_username = local.postgres_username
  postgres_password = local.postgres_password
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
  value     = "postgres://${urlencode(local.postgres_username)}:${urlencode(local.postgres_password)}@${module.onyx.postgres_address}:${module.onyx.postgres_port}/${module.onyx.postgres_db_name}"
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
| Main EKS node group | m7i.2xlarge ×1–3³ | m7i.4xlarge ×1–5 | m7i.4xlarge ×2–8 |
| Document-index node¹ | none³ | m6i.2xlarge, 100 GB | r6i.4xlarge, 512 GB |
| RDS Postgres | db.t4g.large, 64→256 GB | db.t4g.large, 128→512 GB | db.m7g.xlarge, 256→1024 GB |
| ElastiCache Redis | cache.m6g.large | cache.m6g.xlarge | cache.m6g.2xlarge |
| OpenSearch data² | r7g.large.search ×1, 256 GB | r8g.xlarge.search ×1, 512 GB | r8g.2xlarge.search ×1, 1 TB (12k IOPS) |
| OpenSearch masters² | 3× m7g.medium.search | 3× m7g.medium.search | 3× m7g.medium.search |

Pair each tier with the matching sizing snippets from the Helm chart's
`deployment/helm/charts/onyx/SIZING.md` (chart ≥ 0.8.0) — the tiers here size the
infrastructure, the chart snippets size the workloads on it.

¹ The dedicated index node group only matters when running the document index in-cluster
(the Helm chart's bundled OpenSearch StatefulSet). It is created tainted
(`vespa-dedicated=true`), so the StatefulSet must carry the toleration *and* nodeSelector
from SIZING.md's placement snippet to use it. If you point the chart at a managed
OpenSearch domain instead (`enable_opensearch = true` + disable the bundled OpenSearch in
chart values), set `vespa_node_enabled = false` so the node group isn't created at all.
² Only created when `enable_opensearch = true`. All tiers default to a single data node
without zone awareness; RDS is likewise single-AZ. For HA, set
`opensearch_instance_count = 3`, `opensearch_zone_awareness_enabled = true` (and optionally
`opensearch_multi_az_with_standby_enabled = true`).
³ The small tier creates no index node group — the small chart sizing fits the in-cluster
index on the main nodes. With chart ≥ 0.8.0 and SIZING.md's small snippets the whole stack
fits one m7i.2xlarge (external Postgres/Redis/S3); with plain chart defaults the
autoscaler settles at two nodes. Set `vespa_node_enabled = true` to add the dedicated
node back.

These defaults are calibrated from Onyx's own managed production fleet: memory, not CPU, is
the binding dimension on the Kubernetes side, and the burstable `db.t4g.large` holds up to
roughly the medium tier before CPU peaks make a fixed-performance class worthwhile.

Every value in the table is just a default — any sizing variable set to a non-null value
(e.g. `postgres_instance_type`, `opensearch_instance_type`, `main_node_max_size`) overrides
its tier.

**Upgrading from a pre-sizing version of these modules:** the previous hardcoded defaults
were `db.t4g.large` with 20 GB gp2 and no storage autoscaling, `cache.m6g.xlarge`, and a
3×r8g.large multi-AZ OpenSearch domain. The default `medium` tier keeps the same EKS node
groups and Redis node type, and grows Postgres storage online (gp2→gp3 conversion is also
online; storage can never shrink).

⚠️ If you enabled OpenSearch and relied on the old defaults, applying `medium` **replaces
the domain and loses its index data**: a single-AZ domain must live in exactly one subnet,
and the Terraform AWS provider marks `vpc_options` as ForceNew, so the 3-subnet → 1-subnet
change destroys and recreates the domain (capacity-only changes that don't touch subnets —
instance type/count, masters, EBS — are in-place blue/green updates). To keep the old
topology, pin it explicitly: `opensearch_instance_count = 3`,
`opensearch_zone_awareness_enabled = true`, `opensearch_multi_az_with_standby_enabled =
true`, `opensearch_dedicated_master_type = "m7g.large.search"`,
`opensearch_instance_type = "r8g.large.search"`. To adopt the new shape on an existing
domain, take a manual snapshot first and plan a restore. Either way, check `terraform
plan` for `-/+ destroy and then create replacement` on the domain before applying.

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
  - `cluster_name`, `oidc_provider`, `oidc_provider_arn`, `workload_irsa_role_arn`
  - `postgres_endpoint`, `postgres_port`, `postgres_db_name`, `postgres_username` (sensitive), `postgres_dbi_resource_id`
  - `redis_connection_url` (sensitive): hostname:port
  - `opensearch_endpoint`, `opensearch_dashboard_endpoint`, `opensearch_domain_arn` (null unless `enable_opensearch`)

Inputs (common):
- `name` (default `onyx`), `region` (default `us-west-2`), `tags`
- `size` (`small`/`medium`/`large`, default `medium`) — see "T-shirt sizing" above — plus per-setting overrides (`main_node_*`, `vespa_node_*`, `postgres_instance_type`, `postgres_storage_gb`, `redis_instance_type`, `opensearch_*`)
- `postgres_username`, `postgres_password`, `postgres_multi_az`
- `redis_auth_token`: required unless `enable_redis_iam_auth` is true, because the
  Redis module enables transit encryption and AWS requires a token in that case
- `create_vpc` (default true) or existing VPC details and `s3_vpc_endpoint_id`
- `single_nat_gateway` (default false): one NAT gateway per AZ. Set true to trade AZ independence for cost
- WAF controls such as `waf_allowed_ip_cidrs`, `waf_common_rule_set_count_rules`, rate limits, geo restrictions, and logging retention
- Optional OpenSearch controls such as `enable_opensearch`, sizing, credentials, and log retention
- `alarm_actions`: SNS topic ARNs for the CloudWatch alarms created by the data-plane modules. Empty (the default) leaves the alarms in place but notifying nothing
- Optional extras: `enable_upload_bucket`, `enable_gpu_node`, `enable_network_policy`, `enable_craft`

### `vpc`
- Builds a VPC sized for EKS with multiple private and public subnets
- Creates an S3 gateway VPC endpoint (`create_s3_vpc_endpoint`, default true)
- Publishes VPC flow logs to CloudWatch with a minimal IAM role
- Outputs: `vpc_id`, `private_subnets`, `public_subnets`, `vpc_cidr_block`, `nat_gateway_public_ips`, `s3_vpc_endpoint_id`

### `eks`
- Creates the EKS cluster and node groups
- Enables addons: EBS CSI driver, metrics server, cluster autoscaler
- Optionally configures IRSA for S3 access to specified buckets
- Outputs: `cluster_name`, `cluster_endpoint`, `cluster_certificate_authority_data`,
  `oidc_provider`, `oidc_provider_arn`, `cluster_security_group_id`, `node_security_group_id`,
  and `workload_irsa_role_arn` / `workload_irsa_service_account_subjects` when `s3_bucket_names` is set

Key inputs include:
- `cluster_name`, `cluster_version` (default `1.33`)
- `vpc_id`, `subnet_ids`
- `public_cluster_enabled` (default true), `private_cluster_enabled` (default true)
- `cluster_endpoint_public_access_cidrs` (default `[]`). Empty denies all public API access. Set it when `public_cluster_enabled` is true and you need to reach the API server
- `eks_managed_node_groups` (defaults include a main and a vespa-dedicated group with GP3 volumes)
- `s3_bucket_names` (optional list). If set, creates an IRSA role and Kubernetes service account for S3 access

### `postgres`
- Amazon RDS for PostgreSQL with parameterized instance size, storage, version
- Accepts VPC/subnets and ingress CIDRs; returns a ready-to-use connection URL
- Creates CloudWatch alarms for CPU, freeable memory, free storage, IOPS, and
  connection count. Set `alarm_actions` to an SNS topic ARN to be notified;
  leave it empty and the alarms exist but notify nothing

### `redis`
- ElastiCache for Redis (transit encryption enabled by default)
- Supports optional `auth_token`, IAM authentication, and instance sizing
- Creates CloudWatch alarms for memory usage, engine CPU, and swap. Set
  `alarm_actions` to route them to SNS
- Outputs endpoint, port, and whether SSL is enabled

### `s3`
- Creates an S3 bucket for file storage with versioning, server-side encryption
  (`aws:kms`, or `AES256` when anonymous read is enabled), a public access block,
  and lifecycle rules for noncurrent versions, expiration, and IA transition
- Attaches a bucket policy only when one is needed. Access can be scoped to an S3
  gateway VPC endpoint (`s3_vpc_endpoint_id`), and optionally to source IPs or VPCs
  (`allow_anonymous_read` with `allowed_source_ips` / `allowed_vpc_ids`)

### `opensearch`
- Creates an Amazon OpenSearch domain inside the VPC
- Supports custom subnets, security groups, fine-grained access control, encryption, and CloudWatch log publishing
- Creates CloudWatch alarms for cluster status, node count, free storage, JVM
  memory pressure, and write-blocked indices. Set `alarm_actions` to route them to SNS
- Outputs domain endpoints, ARN, and the managed security group ID when it creates one

## Upgrading from an earlier version of these modules

These modules were realigned with the versions Onyx runs in production. If you
applied an earlier revision, note the following before your next `terraform apply`.

**Renamed resources are handled for you.** The modules ship `moved` blocks that
relabel state in place, so the plan shows moves rather than destroy/create:

| Module | Old address | New address |
|---|---|---|
| `s3` | `aws_s3_bucket.bucket` | `aws_s3_bucket.this` |
| `s3` | `aws_s3_bucket_policy.bucket_policy` | `aws_s3_bucket_policy.anonymous_read[0]` |
| `vpc` | `aws_vpc_endpoint.s3` | `aws_vpc_endpoint.s3[0]` |
| `redis` | `aws_security_group.redis_sg` | `aws_security_group.redis_sg[0]` |
| `postgres` | `aws_db_subnet_group.this` | `aws_db_subnet_group.this[0]` |
| `postgres` | `aws_security_group.this` | `aws_security_group.this[0]` |

**Review the plan before applying.** Expect in-place updates where the new
modules add settings the old ones did not manage:
- `s3` now manages versioning, encryption, a public access block, and lifecycle rules
- `vpc` now creates flow logs and their IAM role
- `postgres`, `redis`, and `opensearch` now create CloudWatch alarms
- `postgres` now manages Multi-AZ (default false). If you enabled a standby
  outside Terraform, set `postgres_multi_az = true` on the `onyx` module (or
  `multi_az` on the `postgres` module) before applying, or the standby is removed
- `eks` now enables the private API endpoint by default (`private_cluster_enabled`).
  This is additive and does not remove public access

**`cluster_endpoint_public_access_cidrs` now defaults to `[]`.** If you relied on
the previous default, set the value explicitly before applying.

**The Craft sandbox node group's key changed** from `craft_sandbox` to `sandbox`.
A `moved` block handles the relabel, so the group is not recreated.

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
