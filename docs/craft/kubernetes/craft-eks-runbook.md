# Onyx Craft on EKS: infrastructure and migration runbook

How to stand up Onyx + Craft on a brand-new EKS cluster, and how to migrate existing
manual Craft/EKS setups onto the codified Terraform + Helm path. This assumes a
single-tenant model with managed RDS, ElastiCache, OpenSearch, and S3.

Validated end-to-end on `roshan-craft-test` (us-west-2): `terraform apply` + `helm install` →
Craft provisions a sandbox + snapshot/restore, with no manual kubectl/RBAC/node steps.

---

## 0. Terraform vs Helm — who creates what

**Clean seam: Terraform = AWS infrastructure; Helm = everything inside Kubernetes. Terraform's outputs are Helm's inputs.**

**Terraform** (`deployment/terraform/…`) creates ONLY AWS resources:
- VPC / subnets / NAT; EKS **cluster** + **node groups** (main, vespa, **sandbox** — labeled/tainted/IMDSv2) + the **OIDC provider**; EKS add-ons + gp3 storage class.
- Managed data stores: **RDS** (Postgres), **ElastiCache** (Redis), **OpenSearch** domain; **S3** buckets (file-store + sandbox snapshots); **WAF**.
- IAM/IRSA **roles**: the workload role (S3/RDS) + `SandboxFileSyncRole` (`craft_sandbox` module).
- **Outputs** (the only thing Helm consumes): cluster name, RDS/Redis/OpenSearch endpoints, S3 bucket names, the IRSA **role ARNs**, the OIDC provider ARN/URL.

**Helm** (`deployment/helm/charts/onyx`) creates ONLY Kubernetes objects:
- All in-cluster workloads (api, web, nginx, celery, model servers, code-interpreter, **sandbox-proxy**).
- The **`onyx-sandboxes`** namespace (`templates/sandbox-namespace.yaml`) + **`sandbox-file-sync` SA** + sandbox RBAC (`<release>-<release-namespace>-sandbox-manager`, `<release>-<release-namespace>-proxy-resolve`) (`templates/sandbox-rbac.yaml`).
- `configMap` + secrets that **point the app at the terraform-created endpoints** (POSTGRES_HOST, REDIS_HOST, OpenSearch host, S3 buckets) and carry the IRSA role ARNs.

**Neither crosses over:** Terraform never deploys app workloads or app RBAC; Helm never creates AWS resources — it only *references* them via values you pass from terraform outputs.

**The handoff (terraform output → helm value):**
| terraform output | helm value / use |
|---|---|
| `cluster_name` | `aws eks update-kubeconfig` (then helm targets the cluster) |
| `postgres_endpoint` / redis / `opensearch_endpoint` | `configMap.POSTGRES_HOST` / `REDIS_HOST` / `OPENSEARCH_HOST` |
| file-store + sandbox bucket names | `configMap.S3_FILE_STORE_BUCKET_NAME` / `SANDBOX_S3_BUCKET` |
| `sandbox_file_sync_role_arn` (craft_sandbox) | `craft.sandboxFileSyncRoleArn` → sandbox SA annotation |
| workload role ARN | `serviceAccount.annotations` (recommended) |

> ⚠️ The one currently-blurred boundary: today the **eks module also creates the `onyx` namespace + the
> `onyx-workload-access` SA** (so terraform reaches into k8s). The recommended end state (see §6) is to move
> both to Helm (`--create-namespace` + `serviceAccount.create`/`annotations`), leaving terraform with AWS only.
> This is tracked under the remaining-work section.

## 1. What Craft adds

Craft needs infrastructure that a normal Onyx deployment does not need because it
runs untrusted code in short-lived Kubernetes pods and persists their workspace
state through snapshots.

### Runtime model

When a Craft sandbox starts, the application code creates a sandbox pod in
`onyx-sandboxes`. That pod has:

- a `sandbox` container, which runs the user-facing agent/code environment;
- a `sidecar` container, which runs the push daemon and snapshot API;
- a shared `emptyDir` workspace mounted at `/workspace/sessions`;
- a ConfigMap-backed proxy CA bundle;
- a pod-level `eks.amazonaws.com/skip-containers: sandbox` annotation so IRSA
  credentials are injected into the sidecar but not the untrusted sandbox container;
- `nodeSelector: onyx.app/workload=sandbox`;
- a matching `workload=sandbox:NoSchedule` toleration.

The sandbox manager also creates a per-sandbox ClusterIP Service for opencode,
the push daemon, and Next.js dev-server ports, plus a per-sandbox Secret for
opencode auth/config.

### AWS/Terraform additions

| Resource | Required? | Purpose |
|---|---:|---|
| `modules/aws/craft_sandbox` | Yes for EKS snapshot support | Creates or references the sandbox snapshot bucket, creates the S3 IAM policy, and creates the IRSA role trusted by `system:serviceaccount:onyx-sandboxes:sandbox-file-sync`. |
| Sandbox snapshot S3 bucket | Yes, but may already exist | Stores workspace snapshots. Use `create_bucket=false` when migrating an existing bucket. |
| S3 bucket hardening | Only when Terraform creates the bucket | Enables SSE, blocks public access, and aborts incomplete multipart uploads after 7 days. Existing buckets are not modified when `create_bucket=false`. |
| `SandboxFileSyncRole-*` IAM role | Yes | Lets the sandbox file-sync ServiceAccount access the snapshot bucket without static AWS keys. |
| S3 IAM policy | Yes | Grants `GetObject`, `PutObject`, `DeleteObject`, `AbortMultipartUpload`, and `ListBucket` on the snapshot bucket. |
| EKS OIDC outputs | Yes | Let the `craft_sandbox` module build IRSA trust without an EKS data source, so fresh apply and destroy both work. |
| Optional Craft sandbox node group | Strongly recommended | Gives sandbox pods dedicated, tainted, IMDS-hardened nodes. Existing labeled/tainted nodes can satisfy the same scheduling contract. The Terraform node group uses the upstream shared node SG and intentionally does not also attach the EKS primary cluster SG. |

### Helm/Kubernetes additions

| Object | Namespace | Required? | Purpose |
|---|---|---:|---|
| `Namespace/onyx-sandboxes` | cluster | Yes | Keeps runtime sandbox pods/services/secrets separate from app workloads. |
| `ServiceAccount/sandbox-file-sync` | `onyx-sandboxes` | Yes on EKS | Annotated with `craft.sandboxFileSyncRoleArn`; used by sandbox pods for sidecar S3 access. |
| `Role/<release>-<release-namespace>-sandbox-manager` | `onyx-sandboxes` | Yes | Allows the Onyx workload SA to manage sandbox pods, services, secrets, exec, and logs. |
| `RoleBinding/<release>-<release-namespace>-sandbox-manager` | `onyx-sandboxes` | Yes | Binds sandbox-management permissions to `onyx.serviceAccountName` and `craft.extraBoundServiceAccounts`. |
| `Role/<release>-<release-namespace>-proxy-resolve` | proxy namespace | Yes | Allows service lookup for resolving `SANDBOX_PROXY_HOST` to a ClusterIP. |
| `RoleBinding/<release>-<release-namespace>-proxy-resolve` | proxy namespace | Yes | Binds proxy service lookup to the same workload SAs. |
| `Deployment/onyx-sandbox-proxy` | release namespace | Yes for proxied egress | Runs the egress proxy/gate. |
| `Service/onyx-sandbox-proxy` | release namespace | Yes for proxied egress | Stable in-cluster address for sandbox traffic. |
| `ServiceAccount/onyx-sandbox-proxy` | release namespace | Yes for proxy | Identity used by the proxy deployment. |
| Proxy CA `Role`/`RoleBinding` | release namespace | Yes for proxy CA | Lets the proxy read/create its CA Secret. |
| Proxy sandbox `Role`/`RoleBinding` | `onyx-sandboxes` | Yes for proxy | Lets the proxy watch sandbox pods and write the CA ConfigMap. |
| `NetworkPolicy/onyx-sandbox-proxy` | release namespace | Strongly recommended | Allows only the sandbox namespace to reach the proxy port. |
| `NetworkPolicy/onyx-sandbox-push` | `onyx-sandboxes` | Strongly recommended | Allows only API server and scheduled-task worker pods to reach sandbox push/opencode/Next.js ports. |
| `PodDisruptionBudget/onyx-sandbox-proxy` | release namespace | Availability only | Keeps multi-replica proxy deployments from voluntary disruption all at once. |

### Helm values added by this PR

| Value | Required? | Meaning |
|---|---:|---|
| `craft.sandboxFileSyncRoleArn` | Yes when `ENABLE_CRAFT=true` on EKS | The `craft_sandbox.role_arn` Terraform output; annotated onto `sandbox-file-sync`. |
| `craft.extraBoundServiceAccounts` | Only for additional managers | Extra release-namespace ServiceAccounts that should manage sandboxes. |
| `sandboxProxy.*` | Existing Craft proxy config | Controls sandbox proxy replicas, ports, resources, CA names, scheduling, and security context. |

## 2. How the sandbox node group works

The sandbox node group is an optional EKS managed node group dedicated to Craft
sandbox pods. It is enabled with:

```hcl
enable_craft_sandbox_node_group = true
```

Terraform creates a node group with:

```yaml
labels:
  onyx.app/workload: sandbox
taints:
  - key: workload
    value: sandbox
    effect: NO_SCHEDULE
```

The sandbox manager creates every sandbox pod with:

```yaml
nodeSelector:
  onyx.app/workload: sandbox
tolerations:
  - key: workload
    operator: Equal
    value: sandbox
    effect: NoSchedule
```

That means:

- sandbox pods can only schedule onto nodes labeled `onyx.app/workload=sandbox`;
- normal Onyx pods cannot schedule onto the sandbox nodes because they do not
  tolerate `workload=sandbox:NoSchedule`;
- existing manually created nodes can work if they have the same label and taint;
- the Terraform node group is the repeatable/codified version of that manual setup.

The node group also sets:

```hcl
http_tokens                 = "required"
http_put_response_hop_limit = 1
```

This hardens access to EC2 Instance Metadata Service. It is not what gives the
sidecar S3 permissions; IRSA does that. It is defense-in-depth so untrusted code
cannot easily reach node metadata credentials.

Security-group composition matters too. Regular managed node groups get the
shared node security group from the upstream EKS module, and the sandbox node
group follows that shape. Do not also attach the EKS primary cluster SG: the
upstream module tags the shared node SG and EKS tags the primary cluster SG with
`kubernetes.io/cluster/<name>`, so attaching both to the same nodes breaks
controllers that expect exactly one cluster-tagged node security group.

## 3. Deploy on a fresh cluster

Prereqs: `terraform` (HashiCorp tap), `kubectl`, `helm`, `aws`. AWS auth via SSO — before every
terraform/aws command (SSO static-key shadow + ~daily token expiry):
```bash
aws login   # or: aws sso login --sso-session <session>
eval "$(aws configure export-credentials --profile <profile> --format env)"; unset AWS_PROFILE
```

```bash
# 1. Infra (root module instantiates modules/aws/onyx + modules/aws/craft_sandbox)
cd deployment/terraform/<root>
terraform init && terraform apply           # ~25-35 min (RDS + OpenSearch are the long poles)

# 2. kubeconfig
aws eks update-kubeconfig --name $(terraform output -raw cluster_name) --region <region>

# 3. App (point chart configMap at the managed-service endpoints from terraform outputs)
cd ../../helm/charts/onyx && helm dependency build
helm upgrade --install onyx . -n onyx -f <values> \
  --set craft.sandboxFileSyncRoleArn="$(terraform -chdir=<root> output -raw sandbox_file_sync_role_arn)" \
  --set auth.postgresql.values.password=<rds pw> \
  --set auth.userauth.values.user_auth_secret="$(openssl rand -hex 32)" \
  --set configMap.OPENSEARCH_ADMIN_PASSWORD=<opensearch pw> \
  --set auth.sandboxPushSecret.values.private_key="$(<gen ed25519, see values.yaml comment>)"

# 4. Runtime app config (UI): register first user (becomes admin), add an LLM provider.
# 5. kubectl port-forward -n onyx svc/onyx-nginx-controller 8080:80  → http://localhost:8080
```

Example root-module shape for the Craft-specific Terraform:

```hcl
module "craft_sandbox" {
  source = "../modules/aws/craft_sandbox"

  cluster_name      = module.onyx.cluster_name
  oidc_provider_arn = module.onyx.oidc_provider_arn
  oidc_provider     = module.onyx.oidc_provider

  bucket_name   = "<sandbox-snapshot-bucket>"
  create_bucket = true
  tags          = local.merged_tags
}

output "sandbox_file_sync_role_arn" {
  value = module.craft_sandbox.role_arn
}

output "sandbox_snapshot_bucket_name" {
  value = module.craft_sandbox.bucket_name
}
```

### Required managed-service wiring (chart `configMap`)
Point at the terraform endpoints; disable in-cluster deps:
- `postgresql.enabled/redis.enabled/opensearch.enabled/minio.enabled: false`; `serviceAccount.name: onyx-workload-access` (IRSA), `auth.objectstorage.enabled: false`.
- RDS: `POSTGRES_HOST`, `PGSSLMODE=require`. ElastiCache: `REDIS_HOST`, `REDIS_SSL=true`, `REDIS_SSL_CERT_REQS=none`, `auth.redis.enabled=false` (no auth token).
- OpenSearch (v4.0 search backend): `ONYX_DISABLE_VESPA=true`, `ENABLE_OPENSEARCH_INDEXING/RETRIEVAL_FOR_ONYX=true`, `USING_AWS_MANAGED_OPENSEARCH=true`, `OPENSEARCH_REST_API_PORT=443`, `OPENSEARCH_USE_SSL=true`, `OPENSEARCH_ADMIN_USERNAME=admin`.
- S3: `S3_FILE_STORE_BUCKET_NAME`, `S3_ENDPOINT_URL=""`, `AWS_REGION_NAME`.
- Craft: `ENABLE_CRAFT=true`, `SANDBOX_API_SERVER_URL=http://onyx-api-service.onyx.svc.cluster.local:8080`, `SANDBOX_S3_BUCKET`, `auth.sandboxPushSecret.enabled=true`. (`SANDBOX_SERVICE_ACCOUNT_NAME`/`SANDBOX_CONTAINER_IMAGE` default correctly.)

### Images
`global.version: craft-edge` (backend/web/model-server — the moving Craft build; stable v4.0.x has no
Craft). `code-interpreter`: `latest` (no craft-edge tag). Sandbox image default tracks the current
`onyxdotapp/sandbox:vX.Y.Z`.

---

## 4. Migrating an existing manual Craft/EKS setup

Existing setups usually already have some combination of: a snapshot bucket, an
IAM role, a manually annotated ServiceAccount, sandbox RBAC, and manually
labeled/tainted sandbox nodes. The migration is to make Terraform own AWS/IAM
and Helm own Kubernetes objects without changing the runtime contract.

### Existing snapshot bucket

Do not recreate the bucket. Configure:

```hcl
module "craft_sandbox" {
  source = "../modules/aws/craft_sandbox"

  cluster_name      = module.onyx.cluster_name
  oidc_provider_arn = module.onyx.oidc_provider_arn
  oidc_provider     = module.onyx.oidc_provider

  bucket_name   = "<existing-bucket>"
  create_bucket = false
  tags          = local.merged_tags
}
```

With `create_bucket=false`, Terraform does not create or modify the bucket. It
still creates the IAM policy and IRSA role that allow `sandbox-file-sync` to use
that bucket. Then pass both pieces to Helm:

```bash
helm upgrade --install onyx deployment/helm/charts/onyx \
  -n onyx \
  -f your-values.yaml \
  --set craft.sandboxFileSyncRoleArn="$(terraform output -raw sandbox_file_sync_role_arn)" \
  --set configMap.SANDBOX_S3_BUCKET="<existing-bucket>"
```

Until these chart changes are released, deploy from the local chart path
(`deployment/helm/charts/onyx`). Do not edit chart templates manually; set values.

### Existing manual sandbox node group

Craft does not require the Terraform-created node group specifically. It requires
nodes that satisfy the sandbox pod scheduling contract:

```bash
kubectl get nodes -l onyx.app/workload=sandbox
kubectl describe node <sandbox-node> | rg 'Taints|workload=sandbox'
```

If the existing node group already has:

- label `onyx.app/workload=sandbox`;
- taint `workload=sandbox:NoSchedule`;
- acceptable IMDS hardening;
- the same security-group shape as regular managed node groups: the shared node
  SG, without also attaching another `kubernetes.io/cluster/<name>`-tagged SG;

then leave `enable_craft_sandbox_node_group=false` and keep using those nodes.
If you want Terraform to own the node group, either import the existing node
group into Terraform state or create a Terraform-managed node group with a
non-conflicting name and drain/remove the manual one after sandboxes move.

Do not enable the Terraform node group with the same name as an existing manual
node group unless you are intentionally importing that resource. Otherwise the
apply can fail or create duplicate capacity.

### Existing manual Kubernetes objects

The chart now owns these Kubernetes objects when `ENABLE_CRAFT=true`:

- `namespace/onyx-sandboxes`;
- `serviceaccount/sandbox-file-sync`;
- `role/<release>-<release-namespace>-sandbox-manager`;
- `rolebinding/<release>-<release-namespace>-sandbox-manager`;
- `role/<release>-<release-namespace>-proxy-resolve`;
- `rolebinding/<release>-<release-namespace>-proxy-resolve`;
- sandbox proxy ServiceAccount, Roles, RoleBindings, Deployment, Service, PDB,
  and NetworkPolicy;
- sandbox push/proxy NetworkPolicies.

If those objects were created manually, Helm may refuse to install because they
lack Helm ownership metadata. Prefer a maintenance window where no sandboxes are
running, then replace the manual objects with chart-managed ones:

```bash
kubectl -n onyx-sandboxes get pods,svc,secret
kubectl -n onyx-sandboxes delete role onyx-sandbox-manager onyx-onyx-sandbox-manager --ignore-not-found
kubectl -n onyx-sandboxes delete rolebinding onyx-sandbox-manager onyx-onyx-sandbox-manager --ignore-not-found
kubectl -n onyx-sandboxes delete serviceaccount sandbox-file-sync --ignore-not-found
kubectl -n onyx delete role onyx-proxy-resolve onyx-onyx-proxy-resolve --ignore-not-found
kubectl -n onyx delete rolebinding onyx-proxy-resolve onyx-onyx-proxy-resolve --ignore-not-found
helm upgrade --install onyx deployment/helm/charts/onyx -n onyx -f your-values.yaml ...
```

The example commands include legacy unqualified names and assume release `onyx`
in namespace `onyx`. For other release namespaces, use the rendered
Role/RoleBinding names from `helm template`.

If you cannot delete the objects, you can adopt them into Helm by adding the
standard Helm ownership labels/annotations, but deletion and recreation is
usually simpler for RBAC/ServiceAccount objects. Do not delete active sandbox
pods or their Services in the middle of a user turn.

### Existing manually annotated `sandbox-file-sync` ServiceAccount

The chart recreates/updates `sandbox-file-sync` with:

```yaml
annotations:
  eks.amazonaws.com/role-arn: <craft.sandboxFileSyncRoleArn>
```

The `skip-containers` annotation belongs on the sandbox pod, not the
ServiceAccount. The runtime pod metadata sets:

```yaml
eks.amazonaws.com/skip-containers: sandbox
```

so the sidecar receives IRSA credentials and the untrusted sandbox container does
not.

### Existing published-chart install

If the published `onyx/onyx` Helm chart does not yet include this PR, install or
upgrade from the local chart in this branch:

```bash
helm dependency build deployment/helm/charts/onyx
helm upgrade --install onyx deployment/helm/charts/onyx -n onyx -f your-values.yaml ...
```

This is a chart-source change, not a values-only change against the old
published chart. Setting `craft.sandboxFileSyncRoleArn` against a chart version
that does not contain `templates/sandbox-namespace.yaml` and
`templates/sandbox-rbac.yaml` will not create the missing namespace,
RBAC/ServiceAccount objects.

### Post-migration checks

```bash
# Terraform outputs exist.
terraform output sandbox_file_sync_role_arn
terraform output sandbox_snapshot_bucket_name

# Helm renders the Craft objects.
helm template onyx deployment/helm/charts/onyx -n onyx -f your-values.yaml \
  --set craft.sandboxFileSyncRoleArn="$(terraform output -raw sandbox_file_sync_role_arn)" \
  --show-only templates/sandbox-namespace.yaml
helm template onyx deployment/helm/charts/onyx -n onyx -f your-values.yaml \
  --set craft.sandboxFileSyncRoleArn="$(terraform output -raw sandbox_file_sync_role_arn)" \
  --show-only templates/sandbox-rbac.yaml

# Workload SA can manage sandboxes.
kubectl auth can-i create pods -n onyx-sandboxes \
  --as system:serviceaccount:onyx:onyx-workload-access
kubectl auth can-i create pods/exec -n onyx-sandboxes \
  --as system:serviceaccount:onyx:onyx-workload-access
kubectl auth can-i get services -n onyx \
  --as system:serviceaccount:onyx:onyx-workload-access

# Sandbox nodes exist if using dedicated scheduling.
kubectl get nodes -l onyx.app/workload=sandbox

# The sandbox file-sync SA has the IRSA role annotation.
kubectl -n onyx-sandboxes get sa sandbox-file-sync -o yaml | rg 'eks.amazonaws.com/role-arn'
```

## 5. Lead infra TODO coverage

The lead infra TODO list in `docs/craft/infra/todos.md` is accounted for as:

| TODO | Status in this PR | Operational note |
|---|---|---|
| Helm sandbox namespace RBAC + ServiceAccount | Covered | Helm owns `onyx-sandboxes` via `sandbox-namespace.yaml`, then owns `sandbox-file-sync`, sandbox manager RBAC, and proxy service lookup RBAC via `sandbox-rbac.yaml` when Craft is enabled. |
| Terraform sandbox object store + workload identity | Covered | `craft_sandbox` creates/references the snapshot bucket and creates the sandbox file-sync IRSA role/policy. Existing buckets use `create_bucket=false`. |
| Node-group security-group composition | Covered | The Terraform sandbox node group uses the upstream shared node SG, matching regular managed node groups while avoiding duplicate `kubernetes.io/cluster/<name>`-tagged SGs on the same nodes. Migrated manual node groups should be checked for the same invariant. |
| Node-group metadata-service hardening | Covered | The Terraform sandbox node group enforces IMDSv2 and hop-limit 1. Migrated manual node groups should match before relying on them. |
| Network firewall defense-in-depth | Not codified here | Still valid. This requires regional network-firewall resources, dedicated firewall subnets, sandbox-subnet route-table updates, RFC1918/metadata denies, and managed threat-intel rules. Track and land independently. |

## 6. Remaining work (not codified)

- **cluster-autoscaler** doesn't scale managed node groups: node groups lack the discovery tags
  (`k8s.io/cluster-autoscaler/enabled`, `…/<cluster>`) and the addon (eks-blueprints 1.16.3) ClusterRole
  lacks `volumeattachments` on k8s 1.33. Workaround = pre-sized node groups (`desired`). Real fix = add
  discovery tags + bump the autoscaler chart.
- **Workload IRSA SA → chart-owned (refactor).** The `eks` module creates the `onyx-workload-access`
  SA (and its namespace) directly, which couples terraform to the app namespace and forces a
  `helm uninstall` before `terraform destroy` (else the namespace deletion hangs on helm finalizers).
  Cleaner: terraform outputs only the workload role ARN; Helm owns the SA + namespace via
  `serviceAccount.create=true` + `serviceAccount.annotations.{eks.amazonaws.com/role-arn}` +
  `--create-namespace` (the chart already supports all three). This mirrors how the sandbox SA already
  works (`craft.sandboxFileSyncRoleArn`) and removes the terraform namespace/SA creation entirely.
- **`craft_sandbox` module** should keep taking OIDC (`oidc_provider_arn`/`oidc_provider`) as inputs,
  NOT via `data.aws_eks_cluster` — the data-source form breaks both fresh apply (cluster not created yet)
  and destroy (cluster gone). (Already fixed; noted so it isn't reverted.)
- **SECURITY — egress proxy is allow-all without a catalog, and forwards link-local IMDS.** The
  `sandbox-proxy` gate logs every request as `policy=off_catalog` and forwards it (verified: `example.com`
  returned the real page; `registry.npmjs.org`/`api.openai.com` → 200). It also forwards `169.254.169.254`
  (IMDS) and `sts.us-west-2.amazonaws.com`. The node-level IMDSv2 `hop_limit=1` blocks *direct* IMDS from a
  sandbox pod (verified: direct `curl` times out, exit 7), but the proxy runs on main nodes (`hop_limit=2`)
  and is an alternate path to node metadata. Hardening: (1) hard-deny link-local/metadata (`169.254.0.0/16`,
  `fd00:ec2::254`) at the proxy regardless of catalog; (2) configure the egress catalog so off-catalog
  defaults to **deny** in prod (today an unconfigured catalog = allow-all monitor mode).
- **BUG — idle-cleanup reaps a sandbox mid-turn → wedged session.** `cleanup_idle_sandboxes` sleeps a
  sandbox judged idle (heartbeat-only) even with a turn in flight → deletes its Service → api-server
  `event_bus` loops on `Name or service not known` (UI freeze), AND the in-flight turn's Redis lock
  `buildpromptslot_{sandbox}_{session}` is left held → after revive, new turns are refused
  (`prompt_slot: concurrent turn in flight`) until the 900s TTL. Fixes: (1) exclude sandboxes holding a
  buildpromptslot lock from idle reaping; (2) release the lock on sleep; (3) make the event_bus
  sleep-aware (stop/auto-revive instead of infinite DNS retry); (4) heartbeat for the duration of a turn.

---

## 7. Notes / gotchas (condensed)

- us-west-1 has only 2 AZs (→ the slice fix). Shared account near the EIP quota → use `single_nat_gateway=true`.
- The `vespa` node group is vestigial in v4.0 (OpenSearch replaced Vespa) — size it small or make it optional.
- `cluster_endpoint_public_access_cidrs=[]` causes a perpetual no-op diff AWS rejects — set explicitly (e.g. `["0.0.0.0/0"]`).
- Codified chart/terraform changes live in the **local** chart, not the published `onyx/onyx` — install from `.` until released.
- LLM provider: configure via admin UI (encrypted in DB) — never `GEN_AI_API_KEY` in a ConfigMap.
- S3 buckets deliberately have no `force_destroy` (so `terraform destroy` can never wipe real snapshot/
  file-store data). To tear down an *ephemeral* cluster, `aws s3 rm` the buckets first, then destroy.
- `sandbox-proxy` is a DB/Redis client, not just a forward proxy: its `gate.py` resolves tenant / sandbox /
  egress-policy from **RDS** (and uses **Redis**) on every request, so it needs the same managed-service
  wiring + network reachability as the app pods. Verified: proxy node SG → RDS:5432 path open and an
  authenticated query succeeds; the gate logs `tenant_id=…/sandbox_id=…` resolved per request.
- Teardown order/gotchas: `helm uninstall` before `terraform destroy` (else the `onyx` namespace hangs on
  finalizers). The VPC CNI can leave orphaned `available` `aws-K8S-*` ENIs that pin the node SG/subnets →
  `destroy` hangs ~15 min then fails on `DependencyViolation`; delete those ENIs, then re-run destroy.

---

## 8. Test harness (this validation — not for the PR)

`deployment/terraform/craft-test/` (root module + `secrets.auto.tfvars`, gitignored) and
`deployment/helm/values-craft-test.yaml` are the throwaway test instance used to validate the above.
Lean sizing: `cache.t4g.micro` Redis, `db.t4g.small` Postgres, `m7i.xlarge` main (desired 3),
single-node `t3.medium.search` OpenSearch, `m5.large` sandbox node, single NAT gateway.

**Validated:** snapshot create → S3 (`{tenant}/snapshots/{session}/{id}.tar.gz`, source only — node_modules
regenerated on revive) and restore-on-revive, both via the `sandbox-file-sync` IRSA against the
`craft_sandbox` bucket; cross-replica opencode-serve session reuse (3 api replicas); chart-rendered RBAC +
terraform sandbox node group replacing all manual steps (Validation A); full from-scratch apply+install
(Validation B: `terraform apply` 121 resources → `helm install` from local chart → register user + LLM →
sandbox provisions on the tainted sandbox node group → snapshot + restore, zero manual kubectl/RBAC/node).
Also verified: direct IMDS from a sandbox pod is blocked (`hop_limit=1`); `sandbox-proxy` reaches RDS
(authenticated query) and gates egress (DB-resolved per request); the file-sync `sidecar` IRSA reads/writes
the bucket via `s5cmd`; **celery** runs the real `cleanup_idle_sandboxes_task` end-to-end — the worker SA
(`onyx-workload-access`, bound to `onyx-onyx-sandbox-manager`) execs into `onyx-sandboxes`, snapshots to S3, and
sleeps the sandbox, then the API restore re-provisions and pulls that celery-made snapshot back.
