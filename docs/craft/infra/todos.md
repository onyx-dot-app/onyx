# Craft Infra TODOs

Things to codify so enabling Craft on a new cluster becomes "set `ENABLE_CRAFT=true` in values.yaml" instead of following a manual setup guide. Each item is independent — ship in any order.

Status in PR 11787:

| Item | Status | Notes |
|---|---|---|
| 1. Helm sandbox RBAC + ServiceAccount | Covered | `templates/sandbox-namespace.yaml` renders the sandbox namespace, and `templates/sandbox-rbac.yaml` renders the `sandbox-file-sync` ServiceAccount, sandbox manager Role/RoleBinding, proxy service lookup Role/RoleBinding, and fails fast when the EKS IRSA role ARN is missing. |
| 2. Terraform sandbox object store + workload identity | Covered | `modules/aws/craft_sandbox` creates or references the snapshot bucket, creates the S3 policy, creates the sandbox file-sync IRSA role, and outputs the role ARN/bucket name for Helm. |
| 3. Node-group security-group composition | Covered | The sandbox managed node group uses the upstream shared node SG, matching regular managed node groups without also attaching the EKS primary cluster SG and creating duplicate `kubernetes.io/cluster/<name>`-tagged SGs on the same nodes. |
| 4. Node-group metadata-service hardening | Covered | The sandbox managed node group sets IMDSv2 required and hop-limit 1. |
| 5. Network firewall | Not codified in this PR | Still valid and still independent. The runbook calls this out as remaining defense-in-depth work because it needs regional firewall subnets, route-table changes, and firewall rule deployment beyond this Terraform/Helm slice. |

## 1. Helm template: sandbox namespace RBAC + ServiceAccount

Render everything in the sandbox namespace required for Craft via the Helm chart when `ENABLE_CRAFT=true`:

- The sandbox ServiceAccount, with the workload-identity role annotation.
- The sandbox-namespace Role granting `pods`, `pods/exec`, `pods/log`, `services`, and `secrets` verbs used by the sandbox manager.
- RoleBinding(s) attaching that Role to whichever workload ServiceAccount(s) call the K8s API to manage sandbox pods (typically the api-server SA and the relevant Celery worker SAs).

Source identifiers (IAM role ARN, bound SA names) from a configurable values block and mark them required so a misconfigured deploy fails fast.

The `eks.amazonaws.com/skip-containers=sandbox` credential-isolation annotation belongs on each sandbox pod's metadata, not on this ServiceAccount. `KubernetesSandboxManager` owns that runtime pod annotation.

This removes the need for manual `kubectl create serviceaccount`, `kubectl annotate`, and `kubectl create rolebinding` steps when onboarding a new cluster. Existing clusters whose Role is currently shipped via raw manifests / external GitOps need a one-time cleanup so the chart becomes the single source of truth.

## 2. Terraform module: sandbox object store + workload-identity role

A shared Terraform module that provisions the cloud-side prerequisites for Craft on a given cluster:

- Optional object-storage bucket for snapshots (with encryption + public-access block)
- IAM policy granting the SA read/write/delete/list on that bucket
- IAM role with a trust policy scoped to the sandbox namespace + SA via the cluster's OIDC provider
- Outputs (`role_arn`, `bucket_name`) to wire into the cluster's Helm values

For migrations with an existing bucket, set `create_bucket=false` and pass the existing bucket name. Terraform will still create the IAM role and policy for that bucket, but it will not create or manage the bucket itself. Existing roles that should become module-managed still need Terraform import.

## 3. Node-group security-group composition

A dedicated sandbox node group must use the same shared node security group shape as the cluster's regular managed node groups. Do not attach both the upstream shared node SG and the EKS primary cluster SG to the same nodes: both SGs are tagged with `kubernetes.io/cluster/<name>`, and AWS Load Balancer Controller expects exactly one matching SG on nodes.

**Acceptance:** the Terraform launch template for the sandbox node group attaches the upstream shared node SG and no second `kubernetes.io/cluster/<name>`-tagged SG.

## 4. Node-group metadata-service hardening

Enforce IMDSv2 with hop-limit 1 on the sandbox node group via Terraform so containers can't reach the instance metadata service. If a cluster's node group is currently managed outside Terraform, converting it is a prerequisite.

**Acceptance:** from inside any sandbox pod, a curl to the metadata service times out.

## 5. Network firewall (defense-in-depth)

Replicate the production network-firewall setup in every region that runs Craft. The firewall should:

- Block egress from sandbox subnets to RFC1918 ranges (lateral movement)
- Block egress to the instance metadata service (belt-and-suspenders with item 4)
- Subscribe to a managed threat-intelligence rule group
- Sit in dedicated firewall subnets with sandbox-subnet route tables pointing `0.0.0.0/0` at the firewall endpoint

**Acceptance:** from inside a sandbox pod, RFC1918 + metadata-service requests fail; normal outbound HTTPS to LLM providers still works.

---

## When items 1–4 land

Onboarding a new Craft cluster becomes:

1. `terraform apply` against the cluster (provisions or references the bucket, creates the role, sets metadata hop-limit).
2. Copy `role_arn` and `bucket_name` from terraform outputs into the cluster's Helm values alongside `ENABLE_CRAFT: "true"`.
3. `helm upgrade` (creates namespace, SA, and sandbox RBAC).

Item 5 is independent and bolts on to any cluster after the rest is in place.
