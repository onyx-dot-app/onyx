# Onyx Azure modules

## Status

These modules are validated against the `azurerm` provider schema and each one
ships a `terraform test` suite that plans it against a mocked provider. They
have not yet been applied to a live subscription. Treat the first deployment as
a first deployment.

## Overview

This directory contains Terraform modules to provision the core Azure
infrastructure for Onyx:

- `vnet`: a virtual network with subnets sized for AKS, a NAT gateway for
  stable egress, and optional flow logs
- `aks`: an AKS cluster with workload identity, node pools for the application
  and the document index, and optional GPU and sandbox pools
- `postgres`: a PostgreSQL Flexible Server on a delegated subnet, its private
  DNS zone, and five metric alerts
- `redis`: an Azure Managed Redis behind a private endpoint, with four metric
  alerts. Off by default, because Onyx cannot use it -- see below
- `storage`: a storage account and container for the Onyx file store, with
  versioning, lifecycle rules and network rules
- `waf`: a regional Web Application Firewall policy for an Application Gateway
- `onyx`: a higher-level composition that wires the above together

Use the `onyx` module for a working cluster with sane defaults. Use the
individual modules when you need more control.

These mirror the AWS modules in `../aws`. Read
[Differences from the AWS modules](#differences-from-the-aws-modules) before
porting a configuration across.

## Consuming these modules from another repository

The quickstart below uses local paths. To consume the modules from somewhere
else, point `source` at this repository and pin a ref:

```hcl
module "vnet" {
  source              = "git::https://github.com/onyx-dot-app/onyx.git//deployment/terraform/modules/azure/vnet?ref=tf-azure/v1.0.0"
  resource_group_name = "onyx-prod"
  location            = "eastus"
}
```

Azure releases are tagged `tf-azure/vX.Y.Z`, versioned independently of both
the AWS modules and Onyx product releases. A commit sha works as a `ref` too,
and is the better choice for automated consumers: a sha cannot be moved, where
a tag can.

Pin something. Without a `ref` Terraform tracks the default branch, so an
unrelated merge can change your infrastructure.

## Quickstart (copy/paste)

Unlike the AWS composition, this module declares no `provider` block. The
`azurerm` provider needs a `features` block and a subscription, both of which
belong to your root module.

```hcl
locals {
  location = "eastus"
  # Supply this from a secret store or TF_VAR_ in anything but a scratch stack.
  postgres_password = "your-postgres-password"
}

provider "azurerm" {
  features {}
  subscription_id = "00000000-0000-0000-0000-000000000000"

  # The storage module turns shared access keys off, so Terraform has to reach
  # the account with your Entra identity rather than with a key.
  storage_use_azuread = true
}

module "onyx" {
  source = "./modules/azure/onyx"

  name     = "onyx"
  location = local.location
  size     = "medium"

  postgres_password = local.postgres_password

  # Required. A public API server with no ranges is reachable from every address
  # on the internet, so the module refuses to build one unless you either
  # restrict it, make the cluster private, or say the exposure is intended.
  api_server_authorized_ip_ranges = ["203.0.113.0/24"]
}

# The kubernetes provider needs the cluster, so it reads its credentials back
# out of the module.
provider "kubernetes" {
  host                   = module.onyx.cluster_host
  cluster_ca_certificate = base64decode(module.onyx.cluster_ca_certificate)
  client_certificate     = base64decode(module.onyx.client_certificate)
  client_key             = base64decode(module.onyx.client_key)
}

output "storage_account_name" {
  value = module.onyx.storage_account_name
}

output "postgres_host" {
  value = module.onyx.postgres_host
}

output "redis_host" {
  value = module.onyx.redis_host
}
```

Then:

```bash
terraform init
terraform apply
```

## T-shirt sizing

`size` sets every compute and data-plane knob together. Any individual sizing
variable set to a non-null value overrides its tier default.

| | small | medium | large |
|---|---|---|---|
| system pool VM | `Standard_D8ds_v5` | `Standard_D16ds_v5` | `Standard_D16ds_v5` |
| system pool nodes | 1-3 | 1-5 | 2-8 |
| index pool VM | `Standard_E4ds_v5` | `Standard_E8ds_v5` | `Standard_E16ds_v5` |
| index pool disk | 256 GiB | 512 GiB | 1024 GiB |
| database SKU | `GP_Standard_D2ds_v5` | `GP_Standard_D2ds_v5` | `GP_Standard_D4ds_v5` |
| database storage | 64 GiB | 128 GiB | 256 GiB |
| cache | `Balanced_B5` (~5 GB) | `Balanced_B10` (~10 GB) | `Balanced_B20` (~20 GB) |

Roughly: small suits pilots and small teams, medium a department or company,
large an org-wide deployment. The index pool is memory-optimised at every tier
because on Azure it carries the document index itself.

### Using an existing network

```hcl
module "onyx" {
  source = "./modules/azure/onyx"

  location               = "eastus"
  create_virtual_network = false

  virtual_network_id         = "/subscriptions/.../virtualNetworks/existing"
  aks_subnet_id              = "/subscriptions/.../subnets/aks"
  postgres_subnet_id         = "/subscriptions/.../subnets/postgres"
  private_endpoint_subnet_id = "/subscriptions/.../subnets/private-endpoints"

  postgres_password               = local.postgres_password
  api_server_authorized_ip_ranges = ["203.0.113.0/24"]
}
```

The postgres subnet must be delegated to
`Microsoft.DBforPostgreSQL/flexibleServers`, and the private endpoint subnet
needs `private_endpoint_network_policies` set to `Disabled`. Without a NAT
gateway on the AKS subnet the composition falls back to letting AKS manage
outbound, and the egress address can then change. If your subnet already has a
NAT gateway, set `aks_outbound_type = "userAssignedNATGateway"` to keep it.

## What each module does

### `onyx`

Creates a resource group, then wires the modules below together with t-shirt
sizing. Its outputs carry everything the Helm chart needs.

### `vnet`

A virtual network and four subnets, keyed by purpose: `aks`,
`private_endpoints`, `postgres` (delegated) and `app_gateway`. A NAT gateway
attaches to the subnets that opt into it, so egress keeps one address.

### `aks`

An AKS cluster with the OIDC issuer and workload identity on, a system pool, a
document-index pool, and optional GPU and Craft sandbox pools. Given a list of
storage accounts it creates a managed identity, federates it to a Kubernetes
service account, and grants it blob data access.

### `postgres`

A Flexible Server on a delegated subnet, so it has no public endpoint, plus the
private DNS zone that makes it resolvable. `prevent_destroy` guards the server
and the database.

### `redis`

An Azure Managed Redis reachable only through a private endpoint.

**Onyx cannot run on it, so `enable_redis` defaults to `false`.** Run Redis in
the cluster instead. Managed Redis is always clustered, and Celery's pidbox
opens a `MULTI` spanning keys in several hash slots, which clustered Redis
rejects with `CROSSSLOT`. `EnterpriseCluster` does not avoid this: it presents
one endpoint but still shards underneath, and it was tried against a live
cache, not assumed. `NoCluster` returns `NotImplemented`. Managed Redis also
offers only database 0, where Onyx wants 0, 14 and 15.

The module stays for anyone who wants a cache for something else.

Azure stopped accepting new **Azure Cache for Redis** instances -- a create now
returns "Azure Cache for Redis is retiring, create Azure Managed Redis instance
instead" -- so this module provisions the managed service. It is a different
resource rather than a renamed one, and the differences show:

- Sizing is one SKU name, `Balanced_B5` for about 5 GB, rather than a tier, a
  family and a capacity.
- It speaks TLS on **10000**, where the retiring service used 6380. There is no
  plaintext port to disable and no minimum TLS version to set.
- Eviction policies are spelled `VolatileLRU`, not `volatile-lru`.
- Clustering is not really a choice. `OSSCluster` shards and needs a
  cluster-aware client, which redis-py is not, so the module asks for
  `EnterpriseCluster`.
- Alerts report under `Microsoft.Cache/redisEnterprise`, and the single-thread
  server load metric is replaced by processor time.

### `storage`

A storage account and a private container. Shared access keys are off by
default: Onyx authenticates with `DefaultAzureCredential`, so no key has to
exist.

### `waf`

A regional WAF policy carrying the OWASP Core Rule Set, the Microsoft bot
manager set, two rate limits, and optional IP allowlisting and geo blocking.
Attach it to an Application Gateway. Front Door uses a different resource,
`azurerm_cdn_frontdoor_firewall_policy`, and cannot take this one.

## Differences from the AWS modules

Most of these follow from the platform rather than from taste.

| | AWS | Azure |
|---|---|---|
| document index | managed OpenSearch domain, or in-cluster | in-cluster only; Azure has no managed OpenSearch, and Azure AI Search is a different API |
| pod identity | IRSA: assume a role from an OIDC subject | federate a managed identity to a service account; same `system:serviceaccount:...` subject |
| cache credential | you supply an auth token | Azure generates the keys; they come back as outputs, read off the database rather than the cluster |
| cache service | ElastiCache | Azure Managed Redis; Azure Cache for Redis is retired and will not accept new instances |
| cluster autoscaler | Helm release plus a ClusterRole patch | part of a node pool |
| GPU device plugin | Helm release | installed by AKS with the driver |
| database storage | any GiB, with a growth ceiling | a fixed ladder of sizes, with auto-grow as a switch |
| memory and storage alerts | bytes free | percent used, so thresholds invert |
| flow logs | on by default, to CloudWatch | opt-in, to a storage account, and needs a Network Watcher |
| WAF logs | log group created by the module | emitted by the Application Gateway the policy attaches to |
| provider config | declared inside the composition | declared by your root module |

### Enabling flow logs

Azure writes flow logs to a storage account and needs a Network Watcher in the
region. The composition creates a second storage account for them, so the
network never depends on the account holding application data:

```hcl
module "onyx" {
  # ...
  enable_flow_logs = true
}
```

Azure creates a Network Watcher named `NetworkWatcher_<region>` in a resource
group called `NetworkWatcherRG` the first time a virtual network appears in a
region. If your subscription has that creation turned off, create one first or
point `network_watcher_name` at yours.

This only applies to a network the composition creates. With
`create_virtual_network = false` it refuses the setting rather than creating a
log storage account that nothing would ever write to; configure the flow log
against your own network instead.

## Installing the Onyx Helm chart (after Terraform)

```bash
az aks get-credentials --resource-group "$(terraform output -raw resource_group_name)" \
  --name "$(terraform output -raw cluster_name)"
```

**Install into the `onyx` namespace.** A Kubernetes service account belongs to
one namespace, and the `aks` module creates the federated one in `onyx`. A
release installed anywhere else references an account that does not exist there,
and the API and Celery pods never start.

Terraform creates the namespace itself, because the service account cannot be
created before it exists and the Helm install happens afterwards. So the release
joins that namespace rather than making its own:

```bash
helm install onyx onyx/onyx --namespace onyx -f values.yaml
```

Set `create_workload_namespace = false` if something else already creates it.

Three pieces of chart configuration are needed. None of them have defaults that
work here, so a plain `helm install` will not pick up the infrastructure
Terraform just built.

### 1. Point the workloads at the federated service account

The `aks` module creates a service account annotated with the managed identity's
client ID. Pods only receive a token if they run under that account **and**
carry the `azure.workload.identity/use` label, which is what the webhook looks
for. Without both, `DefaultAzureCredential` finds no token and every file-store
call fails to authenticate.

```yaml
serviceAccount:
  create: false
  name: onyx-workload-access   # matches the aks module's default, in namespace onyx

# The label is per pod, so it goes on every component that touches the file
# store: the API server and the Celery workers.
api:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_primary:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_heavy:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_light:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_docfetching:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_docprocessing:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_user_file_processing:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_scheduled_tasks:
  podLabels:
    azure.workload.identity/use: "true"
celery_worker_monitoring:
  podLabels:
    azure.workload.identity/use: "true"
celery_beat:
  podLabels:
    azure.workload.identity/use: "true"
```

### 2. Point the file store at the storage account

The outputs line up with the environment the app reads:

| environment variable | output |
|---|---|
| `FILE_STORE_BACKEND` | set to `azure` |
| `AZURE_STORAGE_ACCOUNT_NAME` | `storage_account_name` |
| `AZURE_STORAGE_ACCOUNT_URL` | `storage_account_url` |
| `AZURE_FILE_STORE_CONTAINER_NAME` | `storage_container_name` |

Leave `AZURE_STORAGE_ACCOUNT_KEY` unset. Onyx authenticates with
`DefaultAzureCredential`, which picks up the workload identity from step 1, and
the storage account has shared keys turned off anyway.

### 3. Send the document index to its own node pool

The `aks` module taints the index pool `document-index=true:NoSchedule` so
nothing else lands on it. The OpenSearch subchart sets no tolerations of its
own, so without this it schedules onto the system pool instead and the
dedicated pool sits empty:

```yaml
opensearch:
  nodeSelector:
    onyx.app/workload: document-index
  tolerations:
    - key: document-index
      operator: Equal
      value: "true"
      effect: NoSchedule
```

Set `index_node_pool_enabled = false` if you would rather run the index on the
system pool and skip this.

## Testing

Every module has a `terraform test` suite that plans it against a mocked
provider, so the suites need no Azure subscription and no credentials:

```bash
cd deployment/terraform/modules/azure/vnet
terraform init -backend=false
terraform test
```

They cover the wiring and the input validation, which is where a wrong
argument name or an out-of-range value would otherwise only surface at apply.
They do not prove the modules work against Azure. Only an apply does that.

## Security

- Shared access keys on the storage account are off, and blobs are never
  anonymously readable.
- The database and cache have no public endpoint.
- The cache speaks TLS only; Managed Redis offers no plaintext port at all, and
  the database refuses TLS below 1.2.
- The API server will not be built open. You must set
  `api_server_authorized_ip_ranges`, or `private_cluster_enabled`, or
  `allow_unrestricted_api_server_access` to record that an open control plane is
  what you meant.
- The database will not be built without a way to log in: supply
  `postgres_password`, or turn on `entra_database_authentication_only` together
  with a `database_administrator_object_id`.
- Turn `restrict_storage_to_cluster` on once Terraform runs from inside the
  network. From outside, it locks out whoever manages the container.
