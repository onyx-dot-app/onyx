# Onyx GCP modules

## Status

These modules pass validation against the `google` provider schema. Each one
has a `terraform test` suite that plans it against a mocked provider.

The `onyx` composition has been applied to a live project, and the Onyx Helm
chart runs on it: GKE, Cloud SQL, Memorystore with TLS, and the GCS file store
through Workload Identity. The Cloud Armor policy attaches only through the
opt-in L7 load balancer. See [Serving through an L7 load balancer (Cloud
Armor)](#serving-through-an-l7-load-balancer-cloud-armor). That path has been
applied to a live project too: the certificate issued through the DNS
authorization, and Cloud Armor blocked SQL injection, XSS and path traversal
probes.

## Overview

This directory contains Terraform modules to provision the core GCP
infrastructure for Onyx:

- `vpc`: a custom-mode VPC with one subnet, secondary ranges for pods and
  services, Cloud NAT for egress, flow logs, and Private Service Access for
  Cloud SQL and Memorystore
- `gke`: a regional GKE Standard cluster with Workload Identity, private
  nodes, pools for the application and the document index, optional GPU and
  sandbox pools, and the Onyx namespace and service account
- `postgres`: a Cloud SQL for PostgreSQL instance with a private IP only, and
  five alert policies
- `redis`: a Memorystore for Redis instance with AUTH on, and five alert
  policies
- `gcs`: a bucket for the Onyx file store, with versioning, lifecycle rules
  and public access prevention
- `cloud-armor`: a Cloud Armor policy with the OWASP Core Rule Set, two rate
  limits, and optional IP and country rules
- `l7-ingress`: the address and Certificate Manager certificates for an L7
  load balancer that the GKE Gateway API builds
- `onyx`: a higher-level composition that wires the above together

Use the `onyx` module for a working cluster with sane defaults. Use the
individual modules when you need more control.

These mirror the AWS modules in `../aws` and the Azure modules in `../azure`.
Read [Differences from the AWS and Azure
modules](#differences-from-the-aws-and-azure-modules) before you port a
configuration across.

## Consuming these modules from another repository

The quickstart below uses local paths. To consume the modules from a different
repository, point `source` at this repository and pin a ref:

```hcl
module "vpc" {
  source     = "git::https://github.com/onyx-dot-app/onyx.git//deployment/terraform/modules/gcp/vpc?ref=tf-gcp/v1.0.0"
  project_id = "my-project"
  region     = "us-east1"
}
```

GCP releases have tags of the form `tf-gcp/vX.Y.Z`. Their versions are
independent of the AWS modules (`tf/`), the Azure modules (`tf-azure/`) and
Onyx product releases. A commit sha also works as a `ref`. Automated consumers
should use a sha: no one can move a sha, but someone can move a tag.

Pin something. Without a `ref`, Terraform tracks the default branch, and an
unrelated merge can change your infrastructure.

## Quickstart (copy/paste)

This module declares no `provider` block. Your root module configures the
`google` provider and the `kubernetes` provider.

```hcl
locals {
  project_id = "my-project"
  region     = "us-east1"
  # Supply this from a secret store or TF_VAR_ in anything but a scratch stack.
  postgres_password = "your-postgres-password"
}

provider "google" {
  project = local.project_id
  region  = local.region
}

module "onyx" {
  source = "./modules/gcp/onyx"

  name       = "onyx"
  project_id = local.project_id
  region     = local.region
  size       = "medium"

  postgres_password = local.postgres_password

  # Required. A public API server with no authorized networks is open to every
  # address on the internet. The module refuses to build one unless you
  # restrict it, make it private, or say the exposure is intended. Include the
  # address of the machine that runs terraform apply.
  master_authorized_networks = [
    { cidr_block = "203.0.113.0/24", display_name = "office" },
  ]
}

# An access token for whoever runs Terraform. It is not keyed on the cluster,
# so Terraform can read it at plan time, before the cluster exists.
data "google_client_config" "default" {}

# The composition creates a namespace and a service account, so the kubernetes
# provider needs the cluster. It reads the address and CA from the module.
provider "kubernetes" {
  host                   = module.onyx.cluster_endpoint
  cluster_ca_certificate = base64decode(module.onyx.cluster_ca_certificate)
  token                  = data.google_client_config.default.access_token
}

output "gcs_bucket_name" {
  value = module.onyx.gcs_bucket_name
}

output "postgres_host" {
  value = module.onyx.postgres_host
}

output "redis_host" {
  value = module.onyx.redis_host
}

# The get-credentials command after the apply reads these two.
output "cluster_name" {
  value = module.onyx.cluster_name
}

output "location" {
  value = module.onyx.location
}

# Public CA certificates for the chart's redisTls and postgresTls.
output "redis_server_ca_certs" {
  value = module.onyx.redis_server_ca_certs
}

output "postgres_server_ca_cert" {
  value = module.onyx.postgres_server_ca_cert
}

# Credentials for the chart secrets.
output "postgres_username" {
  value     = module.onyx.postgres_username
  sensitive = true
}

output "redis_auth_string" {
  value     = module.onyx.redis_auth_string
  sensitive = true
}
```

On a new project, enable two APIs before the first plan. The `gke` module
reads the project at plan time, and that read needs Resource Manager. The
composition enables Resource Manager too, but only at apply, which is too late:

```bash
gcloud services enable cloudresourcemanager.googleapis.com serviceusage.googleapis.com \
  --project my-project
```

Then:

```bash
terraform init
terraform apply
```

Run the apply from a machine inside `master_authorized_networks`, or inside the
VPC when `private_endpoint_enabled` is set. The `gke` module creates the `onyx`
namespace and service account through the API server. From any other address
the apply stops at those two resources.

Configure the `kubernetes` provider from the module outputs, as above. Do not
use a `data "google_container_cluster"` keyed on the cluster name: on the first
apply the cluster does not exist, and the read fails at plan. Do not add
`depends_on` to that data source or to the module either. It defers reads to
apply time, and plan values that must be known become unknown. Module outputs
carry the dependency without either problem. The Azure modules use the same
pattern for the same reason.

## T-shirt sizing

`size` sets every compute and data-plane knob together. Any individual sizing
variable set to a non-null value overrides its tier default.

| | small | medium | large |
|---|---|---|---|
| main pool machine | `n2-standard-8` | `n2-standard-16` | `n2-standard-16` |
| main pool nodes | 1-3 | 1-5 | 2-8 |
| index pool machine | `n2-highmem-4` | `n2-highmem-8` | `n2-highmem-16` |
| index pool disk | 256 GB | 512 GB | 1024 GB |
| database tier | `db-custom-2-8192` | `db-custom-2-8192` | `db-custom-4-16384` |
| database disk | 64 GB | 128 GB | 256 GB |
| cache | 5 GB | 10 GB | 20 GB |

Roughly: small suits pilots and small teams, medium a department or company,
large an org-wide deployment. Node counts are for the whole pool, not per zone.
The index pool is memory-optimised at every tier because on GCP it carries the
document index itself.

The tiers size the infrastructure only. For the pod resources at each tier, see
the chart's [SIZING.md](../../../helm/charts/onyx/SIZING.md). Copy only the
`resources` values. Its OpenSearch `nodeSelector` is for EKS; on GKE use the one
in [step 4](#4-send-the-document-index-to-its-own-node-pool).

### Using an existing network

```hcl
module "onyx" {
  source = "./modules/gcp/onyx"

  project_id     = "my-project"
  region         = "us-east1"
  create_network = false

  network_id          = "projects/my-project/global/networks/shared"
  subnet_id           = "projects/my-project/regions/us-east1/subnetworks/gke"
  pods_range_name     = "gke-pods"
  services_range_name = "gke-services"

  postgres_password          = local.postgres_password
  master_authorized_networks = [{ cidr_block = "203.0.113.0/24" }]
}
```

The network must already have a Private Service Access connection, or Cloud
SQL and Memorystore fail to create. The nodes have no public IPs, so the
subnet also needs a Cloud NAT for egress. `enable_flow_logs` does nothing here;
configure flow logs on your own subnet.

## What each module does

### `onyx`

Enables the project APIs, then wires the modules below together with t-shirt
sizing. Its outputs carry everything the Helm chart needs. One
`deletion_protection` switch guards the cluster, database, cache, bucket,
Cloud Armor policy, and the L7 address and DNS authorizations.

### `vpc`

A custom-mode network and one subnet. The subnet has secondary ranges for pods
and services, and Private Google Access, so nodes reach Google APIs without the
NAT. Cloud NAT gives private nodes egress. The module reserves a Private
Service Access range and peers it. Its `private_service_access_network_id`
output arrives only once the peering exists, so Cloud SQL and Memorystore wait
for it.

### `gke`

A regional GKE Standard cluster with Dataplane V2, private nodes, Workload
Identity and the Gateway API. The nodes run as a dedicated service account with
the minimum roles. It creates a main pool, a tainted document-index pool, and
optional GPU and Craft sandbox pools. It also creates the `onyx` namespace and
the `onyx-workload-access` service account.

### `postgres`

A Cloud SQL for PostgreSQL instance with a private IP only, TLS enforced,
backups and point-in-time recovery. It creates the `onyx` database. It sets the
password of the `postgres` user that Cloud SQL ships.

### `redis`

A Memorystore for Redis instance on the Private Service Access range. AUTH is
always on, and TLS is on by default. The eviction policy is `volatile-lru`, because Celery broker keys
carry no TTL and an `allkeys-*` policy would drop queued tasks. RDB snapshots
are on.

### `gcs`

A bucket with uniform access, public access prevention, versioning, and a
lifecycle rule for old versions. It grants the workload identity principal
object access and the narrow read that Onyx needs at startup.

### `cloud-armor`

A backend security policy with the OWASP Core Rule Set at sensitivity 1, an API
rate limit, a global rate limit and Adaptive Protection. It takes effect only on
an L7 load balancer; see below.

The rule sets are tuned the standard way, with request field exclusions, so
they deny without breaking Onyx. Without the tuning, sensitivity 1 denies chat
messages that hold code, shell commands or file paths, every upload, and the
Google sign-in callback.

- No rule set except `methodenforcement`, `scannerdetection` and
  `sessionfixation` reads the values of the Onyx fields that carry chat text,
  prompts, code, URLs and secrets, such as `message`, `system_prompt`,
  `api_base` and `password`. A name covers the query string, a form body and
  the top-level keys of a JSON body, on every path. A nested key is reached
  only through its parent, so free-form objects such as a connector's
  configuration are covered by prefix. Everything else in the request is still
  checked: the path, the headers, the cookies, the other parameters, and the
  parameter names.
- The same rule sets skip an upload, a `POST`, `PUT` or `PATCH` with a
  `multipart/form-data` body. Cloud Armor does not parse a multipart body and
  reads the file content as parameter names, which no exclusion covers. The
  header alone exempts nothing: a `GET` is checked in full whatever it sends.
- `scannerdetection` and `sessionfixation` check every request in full.

When a legitimate request gets a 403, the load balancer log names the
signature and the request. Add the field to
`cloud_armor_extra_uninspected_fields`, or its parent object to
`cloud_armor_extra_uninspected_field_prefixes`. Both add to the module
defaults. The rate limits apply to every request.

### `l7-ingress`

A global external IPv4 address, and a Certificate Manager certificate map with
one Google-managed certificate for each domain. Each certificate uses a DNS
authorization, so Google issues it before DNS points at the load balancer. A
GKE Gateway names the address and the map. Terraform does not create the
Gateway; [Serving through an L7 load balancer (Cloud
Armor)](#serving-through-an-l7-load-balancer-cloud-armor) has the Kubernetes
objects.

## Differences from the AWS and Azure modules

Most of these follow from the platform rather than from taste.

| | AWS | Azure | GCP |
|---|---|---|---|
| document index | managed OpenSearch, or in-cluster | in-cluster only | in-cluster only; GCP has no managed OpenSearch |
| cache | ElastiCache | Azure Managed Redis, off by default | Memorystore for Redis, on by default |
| pod identity | IRSA: assume a role | federate a managed identity to a service account | grant IAM roles straight to the Kubernetes service account |
| WAF attachment | ALB | Application Gateway | opt-in Gateway API load balancer (`enable_l7_ingress`) through a GCPBackendPolicy |
| flow logs | on, to CloudWatch | opt-in, needs a storage account | on, to Cloud Logging |
| project APIs | none | none | enabled by the composition |
| provider config | declared inside the composition | declared by your root module | declared by your root module |

**Managed Redis works here with no extra settings.** Onyx uses database 0 for
the app, 14 for Celery results and 15 for the Celery broker. Memorystore for
Redis is one primary endpoint with the default 16 databases. The Onyx defaults
work unchanged. Azure Managed Redis has only database 0, and the Redis Cluster
products shard keys, which breaks Celery with `CROSSSLOT`. So the composition
turns Memorystore on by default. Set `enable_redis = false` to use the
in-cluster Redis.

**The document index runs in the cluster.** GCP has no managed OpenSearch. The
chart's OpenSearch subchart runs on the tainted index pool.

**Workload Identity needs no Google service account.** GKE Workload Identity
Federation lets IAM name a Kubernetes service account directly. The bucket
grant goes to the `workload_identity_principal` output. There is no Google
service account to impersonate and no annotation on the Kubernetes service
account. Use the same output to grant access to other resources.

**Cloud Armor attaches only to an L7 load balancer.** The chart's
ingress-nginx controller sits behind a Service of type `LoadBalancer`, which is
an L4 passthrough load balancer. That load balancer cannot carry the policy.
The policy then protects nothing, and nothing reports it. This is the same trap
as the Azure WAF policy without an Application Gateway. Turn on
`enable_l7_ingress` and follow [Serving through an L7 load balancer (Cloud
Armor)](#serving-through-an-l7-load-balancer-cloud-armor).

**Cloud Armor counts an API request against the API limit only.** Cloud
Armor stops at the first rule that matches. A request under the path prefix
matches the API rate limit rule and does not reach the global one. On AWS, WAF
counts an API request against both limits.

**Flow logs are on by default.** GCP writes them to Cloud Logging and needs no
extra infrastructure. Azure needs a Network Watcher and a storage account, so
it keeps them off.

**The composition enables the project APIs.** A new project has most of them
off. `enable_project_apis` turns on Compute, GKE, Cloud SQL Admin, Memorystore,
Service Networking, Storage, Monitoring, Logging, IAM and Resource Manager.
With `enable_l7_ingress` it also turns on Certificate Manager. It never turns
them off on destroy, because other workloads may use them.

## Installing the Onyx Helm chart (after Terraform)

```bash
gcloud container clusters get-credentials "$(terraform output -raw cluster_name)" \
  --location "$(terraform output -raw location)" --project my-project
```

**Install into the `onyx` namespace.** A Kubernetes service account belongs to
one namespace, and the `gke` module creates the one with the bucket grant in
`onyx`. A release in a different namespace references an account that does not
exist there, and the API and Celery pods never start.

Terraform creates the namespace itself, because the service account needs it
and the Helm install happens afterwards. So the release joins that namespace
and does not create one:

```bash
helm install onyx onyx/onyx --namespace onyx --version <chart version> -f values.yaml
```

Always set `--version`, and set `global.version` in the values to the Onyx
release. Both default to the newest release.

Set `create_workload_namespace = false` if something else already creates it.

Four pieces of chart configuration are necessary. Their defaults do not work
here, so a plain `helm install` does not use the infrastructure that Terraform
built.

### 1. Point the workloads at the workload service account

The chart runs every Onyx pod, including the API server and the Celery
workers, as `serviceAccount.name`. The bucket grant names that account, so no
pod label and no annotation are necessary. Without it, the pods run as
`default` and every file store call gets `403`.

```yaml
serviceAccount:
  create: false
  name: onyx-workload-access   # the gke module's default, in namespace onyx
```

### 2. Point the file store at the bucket

Turn off the bundled MinIO and set the GCS keys. The chart copies every
non-empty `configMap` key into the pod environment, so no chart change is
necessary.

```yaml
minio:
  enabled: false

configMap:
  FILE_STORE_BACKEND: "gcs"
  GCS_FILE_STORE_BUCKET_NAME: "<gcs_bucket_name output>"
  GCS_PROJECT_ID: "<gcs_project_id output>"
```

Leave `GCS_SERVICE_ACCOUNT_KEY_PATH` and `GCS_SERVICE_ACCOUNT_KEY_JSON` unset.
Onyx then uses Application Default Credentials, which pick up the workload
identity from step 1.

### 3. Point Onyx at Cloud SQL and Memorystore

```yaml
global:
  version: "v4.8.1"              # the Onyx release; the default is latest

postgresql:
  enabled: false

redis:
  enabled: false

configMap:
  POSTGRES_HOST: "<postgres_host output>"
  POSTGRES_PORT: "5432"
  POSTGRES_DB: "onyx"            # postgres_db_name output
  REDIS_HOST: "<redis_host output>"
  REDIS_PORT: "6378"             # redis_port output; 6378 is the TLS port
  WEB_DOMAIN: "https://onyx.example.com"   # the address users open

auth:
  postgresql:
    existingSecret: "onyx-postgresql"   # keys: username, password
  redis:
    existingSecret: "onyx-redis"        # key: redis_password = redis_auth_string output
  opensearch:
    existingSecret: "onyx-opensearch"   # keys: opensearch_admin_username, opensearch_admin_password
  userauth:
    enabled: true
    existingSecret: "onyx-userauth"     # key: user_auth_secret (openssl rand -hex 32)
  objectstorage:
    enabled: false                      # GCS uses Workload Identity, not S3 keys
```

Without the last three entries, `helm install` fails. The chart requires an
OpenSearch admin password and S3 keys, and Onyx needs `USER_AUTH_SECRET`. The
OpenSearch password needs uppercase, lowercase, a digit and a special
character.

Set `POSTGRES_DB`. Without it, Onyx uses the `postgres` database that Cloud SQL
ships, and the `onyx` database stays empty.

Create the secrets in the `onyx` namespace. Do not put the passwords in
`values.yaml`. Terraform supplies the database and Redis credentials. Generate
the OpenSearch and user-auth secrets:

```bash
kubectl -n onyx create secret generic onyx-postgresql \
  --from-literal=username="$(terraform output -raw postgres_username)" \
  --from-literal=password='<postgres_password>'
kubectl -n onyx create secret generic onyx-redis \
  --from-literal=redis_password="$(terraform output -raw redis_auth_string)"
kubectl -n onyx create secret generic onyx-opensearch \
  --from-literal=opensearch_admin_username=admin \
  --from-literal=opensearch_admin_password='Os1!'"$(openssl rand -hex 16)"
kubectl -n onyx create secret generic onyx-userauth \
  --from-literal=user_auth_secret="$(openssl rand -hex 32)"
```

OpenSearch reads its admin password one time, at first start. A later change
to the secret does not change the password.

**Redis uses TLS by default.** `redis_transit_encryption_enabled` is `true`, so
Memorystore serves TLS on port 6378 only. Turn on the chart's `redisTls`. It
sets `REDIS_SSL=true` and makes Onyx verify the server against the CA:

```bash
terraform output -json redis_server_ca_certs | jq -r '.[]' > redis-ca.crt
kubectl -n onyx create configmap onyx-redis-ca --from-file=ca.crt=redis-ca.crt
```

```yaml
redisTls:
  enabled: true
  caConfigMapName: onyx-redis-ca
  caKey: ca.crt
```

The file holds every CA in the output, so a Memorystore CA rotation does not
break the connection. Without `redisTls`, set `REDIS_SSL: "true"` in
`configMap`. Onyx then encrypts, but does not verify the server.

Cloud SQL accepts only encrypted connections, and Onyx encrypts by default, so
Postgres needs no TLS setting. To also verify the server, turn on the chart's
`postgresTls` with the `postgres_server_ca_cert` output:

```bash
terraform output -raw postgres_server_ca_cert > postgres-ca.crt
kubectl -n onyx create configmap onyx-postgres-ca --from-file=ca.crt=postgres-ca.crt
```

```yaml
postgresTls:
  enabled: true
  sslMode: verify-ca
  caConfigMapName: onyx-postgres-ca
  caKey: ca.crt
```

Do not turn on `postgresTls` with Onyx v4.8.x or earlier. Those versions reject
the Cloud SQL server certificate (`Missing Authority Key Identifier`), and the
API server crash-loops. Use `verify-ca`: `verify-full` fails, because the
Cloud SQL certificate does not name the private IP address.

### 4. Send the document index to its own node pool

The `gke` module taints the index pool `document-index=true:NoSchedule`, so
nothing else lands on it. The OpenSearch subchart sets no tolerations of its
own. Without this, it goes onto the main pool and the index pool stays empty:

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

Set `index_node_pool_enabled = false` to run the index on the main pool and
skip this.

### 5. Optional: run the model servers on the GPU pool

`enable_gpu_node_pool = true` only adds the pool. It does not move a model
server. The pool is tainted `nvidia.com/gpu=present:NoSchedule` and labelled
`onyx.app/gpu=true`, so a pod lands there only when it asks. GKE installs the
driver and the device plugin. The model server image already carries CUDA:

```yaml
inferenceCapability:
  nodeSelector:
    onyx.app/gpu: "true"
  tolerations:
    - key: nvidia.com/gpu
      operator: Equal
      value: present
      effect: NoSchedule
  resources:
    limits:
      nvidia.com/gpu: 1

indexCapability:
  nodeSelector:
    onyx.app/gpu: "true"
  tolerations:
    - key: nvidia.com/gpu
      operator: Equal
      value: present
      effect: NoSchedule
  resources:
    limits:
      nvidia.com/gpu: 1
```

Each GPU goes to one pod. The composition's GPU pool is one node with one GPU,
so these values need two GPUs and one pod stays pending. Give the GPU to one
model server only, or use the `gke` module with `gpu_accelerator_count = 2`.
Helm merges `resources` with the chart defaults, so the CPU and memory requests
and limits stay.

## Serving through an L7 load balancer (Cloud Armor)

The chart exposes Onyx through ingress-nginx behind a Service of type
`LoadBalancer`. On GKE that is an L4 passthrough load balancer, and a Cloud
Armor policy cannot attach to it. To put the policy in front of Onyx, serve
through a global external Application Load Balancer instead. The GKE Gateway
API builds that load balancer. The `gke` module already turns the Gateway API
on.

Terraform creates the GCP resources that the Gateway names: a global address,
and a certificate map with one Google-managed certificate for each domain. You
apply the Kubernetes objects yourself. They are CRDs, and a
`kubernetes_manifest` of a CRD fails the plan of a new cluster.

The load balancer sends traffic to the Onyx server block of the chart's nginx,
on port 1024. That is the port the chart's `LoadBalancer` Service uses too.
The API, web server and MCP routes stay in nginx.

### 1. Turn it on in Terraform

```hcl
module "onyx" {
  # ...
  enable_l7_ingress = true
  l7_domains        = ["onyx.example.com"]
}

output "l7_ip_address" {
  value = module.onyx.l7_ip_address
}

output "l7_address_name" {
  value = module.onyx.l7_address_name
}

output "l7_certificate_map_name" {
  value = module.onyx.l7_certificate_map_name
}

output "l7_dns_authorization_records" {
  value = module.onyx.l7_dns_authorization_records
}

output "l7_certificate_names" {
  value = module.onyx.l7_certificate_names
}

output "cloud_armor_policy_name" {
  value = module.onyx.cloud_armor_policy_name
}
```

Use lowercase hostnames with no wildcard. Keep `enable_cloud_armor` on, which
is the default. Run `terraform apply`. The composition turns on the Certificate
Manager API. With `enable_project_apis = false`, turn it on yourself first.

### 2. Add the DNS authorization records

```bash
terraform output -json l7_dns_authorization_records
```

For each domain, add the record at your DNS provider. It is a `CNAME` named
`_acme-challenge.<domain>.`. The record proves that you control the domain. It
does not move traffic, so the current load balancer keeps serving.

### 3. Wait for the certificates

```bash
terraform output -json l7_certificate_names
gcloud certificate-manager certificates describe <certificate name> \
  --location=global --project my-project --format='value(managed.state)'
```

Wait for `ACTIVE` on each certificate. This usually takes minutes, but can take
hours when the DNS provider is slow. `managed.authorizationAttemptInfo` in the
full output tells why a certificate is still `PROVISIONING`.

### 4. Apply the Kubernetes objects

Apply these in the release namespace. Replace the values in `<>` with the
Terraform outputs. The examples use the release name `onyx` and the namespace
`onyx`.

```yaml
# A dedicated Service for the Gateway. Only one GCPBackendPolicy can attach to
# a Service, and the chart's own nginx Service changes type in step 6.
apiVersion: v1
kind: Service
metadata:
  name: onyx-nginx-l7
  namespace: onyx
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: onyx   # the Helm release name
    app.kubernetes.io/component: controller
  ports:
    - name: http
      port: 80
      targetPort: 1024
      protocol: TCP
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: onyx
  namespace: onyx
  annotations:
    networking.gke.io/certmap: <l7_certificate_map_name>
spec:
  gatewayClassName: gke-l7-global-external-managed
  addresses:
    - type: NamedAddress
      value: <l7_address_name>
  listeners:
    # No tls block: the certificate map annotation supplies the certificates.
    - name: https
      protocol: HTTPS
      port: 443
    - name: http
      protocol: HTTP
      port: 80
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: onyx-https
  namespace: onyx
spec:
  parentRefs:
    - name: onyx
      sectionName: https
  hostnames:
    - onyx.example.com   # every l7_domains entry
  rules:
    - backendRefs:
        - name: onyx-nginx-l7
          port: 80
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: onyx-http-redirect
  namespace: onyx
spec:
  parentRefs:
    - name: onyx
      sectionName: http
  hostnames:
    - onyx.example.com
  rules:
    - filters:
        - type: RequestRedirect
          requestRedirect:
            scheme: https
            statusCode: 301
---
# The load balancer probes the pod on 1024 directly. The default probe path
# is "/", which proxies to the web server; /nginx-health answers in nginx.
apiVersion: networking.gke.io/v1
kind: HealthCheckPolicy
metadata:
  name: onyx-nginx-l7
  namespace: onyx
spec:
  default:
    config:
      type: HTTP
      httpHealthCheck:
        portSpecification: USE_FIXED_PORT
        port: 1024
        requestPath: /nginx-health
  targetRef:
    group: ""
    kind: Service
    name: onyx-nginx-l7
---
apiVersion: networking.gke.io/v1
kind: GCPBackendPolicy
metadata:
  name: onyx-nginx-l7
  namespace: onyx
spec:
  default:
    securityPolicy: <cloud_armor_policy_name>
    # The load balancer counts the whole response, not the idle time as nginx
    # does. Chat and deep research stream for many minutes.
    timeoutSec: 3600
    # Cloud Armor writes its decisions to these logs. A GCPBackendPolicy with
    # no logging section turns them off.
    logging:
      enabled: true
      sampleRate: 1000000
  targetRef:
    group: ""
    kind: Service
    name: onyx-nginx-l7
```

The Gateway takes a few minutes to program. `kubectl -n onyx describe gateway
onyx` shows `Programmed: True` when it is ready. Each policy shows `Attached:
True` in its status.

Test the new path before you move DNS:

```bash
curl --resolve onyx.example.com:443:<l7_ip_address> https://onyx.example.com/nginx-health
```

### 5. Tell Onyx its public URL

Onyx marks its cookies `Secure` and builds its login redirects from
`WEB_DOMAIN`. Set it to the HTTPS address:

```yaml
configMap:
  WEB_DOMAIN: "https://onyx.example.com"
```

### 6. Move DNS

Point the `A` record of each domain at `l7_ip_address`. After the old record
expires from caches, the ingress-nginx `LoadBalancer` is no longer used. Make
it a cluster-internal Service. That removes the L4 load balancer and its
public address:

```yaml
nginx:
  controller:
    service:
      type: ClusterIP
```

Certificate Manager now serves the certificate for these hosts. You no longer
need cert-manager, the chart's `letsencrypt`, or the chart's `ingress` for
them.

### Notes

- Cloud Armor sees the real client address here. The rate limits count each
  client separately, and the IP and country rules match the client.
- A domain change adds or removes only that domain's certificate. The other
  domains keep serving.
- `deletion_protection` guards the address and the DNS authorizations. Set it
  to `false` and apply before you remove a domain.
- Raise `timeoutSec` if a single response can stream for longer than an hour.

## Testing

Every module has a `terraform test` suite that plans it against a mocked
provider. The suites need no GCP project and no credentials:

```bash
cd deployment/terraform/modules/gcp/vpc
terraform init -backend=false
terraform test
```

They cover the wiring and the input validation. Without them, a wrong argument
name or an out-of-range value shows only at apply. They do not prove that the
modules work against GCP. Only an apply does that.

## Security

- The bucket has uniform access and enforced public access prevention, so no
  object can become public.
- The database and cache have private IPs only. The database refuses
  unencrypted connections. The cache always requires AUTH and serves TLS by
  default.
- Nodes have no public IPs, run as a dedicated service account with the
  minimum roles, and use shielded VMs. Pods see only their own identity through
  the GKE metadata server.
- The API server will not be built open. Set `master_authorized_networks`, or
  `private_endpoint_enabled`, or `allow_unrestricted_api_server_access` to
  record that an open control plane is what you meant.
- The database will not be built without a password of at least 8 characters.
- `deletion_protection` is on by default for the cluster, database, cache,
  bucket, Cloud Armor policy, and the L7 address and DNS authorizations. Set it
  to `false` and apply before a destroy.
- For a record of who reads the bucket, turn on Cloud Audit Logs Data Access
  for `storage.googleapis.com` on the project or organization. The module does
  not configure it.
