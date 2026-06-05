# Onyx Craft on a fresh EKS cluster

How to stand up Onyx + Craft on a brand-new EKS cluster (single-tenant model: managed RDS +
ElastiCache + OpenSearch + S3), and the chart/terraform changes that make it work out of the box.

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
- The **`onyx-sandboxes`** namespace + **`sandbox-file-sync` SA** + sandbox RBAC (`onyx-sandbox-manager`, `onyx-proxy-resolve`) — `templates/sandbox-rbac.yaml`.
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
> `onyx-workload-access` SA** (so terraform reaches into k8s). The recommended end state (see §3) is to move
> both to Helm (`--create-namespace` + `serviceAccount.create`/`annotations`), leaving terraform with AWS only.

## 1. Changes to ship (product repo)

All backward-compatible — every new variable defaults to the prior behavior; existing consumers
(st-dev, customers) are unaffected.

### Terraform modules (`deployment/terraform/modules/aws/`)

| File | Change | Why |
|---|---|---|
| `vpc/{main,variables}.tf` | `azs = slice(names, 0, min(3, len))`; add `single_nat_gateway` var | `slice(…,0,3)` crashed in 2-AZ regions; per-AZ NAT (3 EIPs) can exhaust the EIP quota |
| `eks/outputs.tf` | Re-export `node_security_group_id`, `cluster_security_group_id` | `enable_opensearch=true` referenced them but they weren't exported (OpenSearch was broken) |
| `eks/main.tf` | Create `kubernetes_namespace` for the IRSA SA before the SA | Fresh cluster has no `onyx` ns yet → SA create failed |
| `eks/{main,variables}.tf` | `main_node_{min,max,desired}_size` vars (desired default 2) | One node doesn't fit the workload; autoscaler isn't relied on for initial size |
| `eks/{main,variables}.tf` | `enable_craft_sandbox_node_group` (+ instance/min/max/desired) → node group labeled `onyx.app/workload=sandbox`, tainted `workload=sandbox:NoSchedule`, IMDSv2 `http_put_response_hop_limit=1` | Sandbox pods have a hardcoded `nodeSelector: onyx.app/workload=sandbox`; IMDS hardening keeps untrusted code off node creds |
| `postgres/{main,variables}.tf` | `deletion_protection` + `skip_final_snapshot` vars | Were hardcoded → dev/throwaway teardown impossible |
| `onyx/{main,variables}.tf` | Forward all of the above + `redis_instance_type`, `postgres_instance_type`, `opensearch_{zone_awareness_enabled,availability_zone_count,auto_tune_enabled}`, `cluster_endpoint_public_access_cidrs` already exposed | The product `onyx` module lagged the cloud module; couldn't run lean or single-node OpenSearch |
| **NEW `craft_sandbox/`** | S3 bucket (SSE, public-access-block, abort-incomplete-MPU) + IAM policy + IRSA role trust-scoped to `system:serviceaccount:onyx-sandboxes:sandbox-file-sync`; outputs `role_arn`, `bucket_name` | Cloud-side prereqs for sandbox snapshot S3 access (was a manual console runbook) |

### Helm chart (`deployment/helm/charts/onyx/`)

| File | Change |
|---|---|
| **NEW `templates/sandbox-rbac.yaml`** | Gated on `ENABLE_CRAFT=true`, renders: `sandbox-file-sync` SA (IRSA `role-arn` + `skip-containers=sandbox`); `onyx-sandbox-manager` Role+RoleBinding in the sandbox ns (pods/exec/attach/portforward/log, services, configmaps, secrets, pvc); `onyx-proxy-resolve` Role+RoleBinding in the proxy ns (services/endpoints read, for SANDBOX_PROXY_HOST ClusterIP resolution). Bound to `onyx.serviceAccountName` + `craft.extraBoundServiceAccounts`. Fails fast if `craft.sandboxFileSyncRoleArn` is unset. |
| `values.yaml` | `craft.sandboxFileSyncRoleArn` (required when Craft on) + `craft.extraBoundServiceAccounts` |

> These two close `docs/craft/infra/todos.md` items #1 (chart SA/RBAC) and #2 (craft_sandbox terraform).

---

## 2. Deploy on a fresh cluster

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

## 3. Remaining work (not codified)

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
- **SECURITY — `skip-containers` on the SA is silently ignored; the untrusted sandbox container holds the
  file-sync IRSA.** `sandbox-rbac.yaml` puts `eks.amazonaws.com/skip-containers: sandbox` on the
  `sandbox-file-sync` **ServiceAccount** to keep AWS creds out of the agent (`sandbox`) container. But the
  `amazon-eks-pod-identity-webhook` reads `skip-containers` from the **pod annotation**, NOT the SA — while
  it reads `role-arn` from the SA (which is why injection happened). The sandbox manager builds the pod with
  no annotations, so `skip-containers` never reaches the webhook → `AWS_ROLE_ARN` + the projected token land
  in **both** containers. Confirmed by a controlled 2-container pod: with `skip-containers` on the *pod*, the
  listed container got no creds and the other did. Net: agent code in the sandbox can assume
  `SandboxFileSyncRole` and read/write/delete the whole snapshot bucket. **Fix:** set the annotation on the
  POD in `kubernetes_sandbox_manager.py` (`V1ObjectMeta`, ~L800): `annotations={"eks.amazonaws.com/
  skip-containers": "sandbox"}`. (The SA-level annotation is dead weight for this — keep or drop.)
  Defense-in-depth (per-tenant prefix-scoped IAM) was weighed and **deferred as overkill**: once the token
  no longer reaches the untrusted container, the bucket-wide policy is only exploitable by compromising the
  trusted sidecar itself. Scoping per-identity isn't a policy edit anyway — all sandboxes share one role, so
  it needs per-tenant roles or EKS Pod Identity + ABAC. Revisit for **MT cloud** if cross-tenant isolation
  guarantees are required.
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

## 4. Notes / gotchas (condensed)

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

## 5. Test harness (this validation — not for the PR)

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
(`onyx-workload-access`, bound to `onyx-sandbox-manager`) execs into `onyx-sandboxes`, snapshots to S3, and
sleeps the sandbox, then the API restore re-provisions and pulls that celery-made snapshot back.
