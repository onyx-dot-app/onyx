# Craft Infra TODOs

Things to codify so enabling Craft on a new cluster becomes "set `ENABLE_CRAFT=true` in values.yaml" instead of following a manual setup guide. Each item is independent — ship in any order.

## 1. Helm template: sandbox namespace RBAC + ServiceAccount

Render everything in the sandbox namespace required for Craft via the Helm chart when `ENABLE_CRAFT=true`:

- The sandbox ServiceAccount, with workload-identity annotations and the `eks.amazonaws.com/skip-containers=sandbox` annotation so only the sidecar container receives cloud credentials.
- The sandbox-namespace Role granting `pods`, `pods/exec`, `services` verbs.
- RoleBinding(s) attaching that Role to whichever workload ServiceAccount(s) call the K8s API to manage sandbox pods (typically the api-server SA and the relevant Celery worker SAs).

Source identifiers (IAM role ARN, bound SA names) from a configurable values block and mark them required so a misconfigured deploy fails fast.

This removes the need for manual `kubectl annotate` and `kubectl create rolebinding` steps when onboarding a new cluster. Existing clusters whose Role is currently shipped via raw manifests / external GitOps need a one-time cleanup so the chart becomes the single source of truth.

## 2. Terraform module: sandbox object store + workload-identity role

A shared Terraform module that provisions the cloud-side prerequisites for Craft on a given cluster:

- Object-storage bucket for snapshots (with encryption + public-access block)
- IAM policy granting the SA read/write/delete/list on that bucket
- IAM role with a trust policy scoped to the sandbox namespace + SA via the cluster's OIDC provider
- Outputs (`role_arn`, `bucket_name`) to wire into the cluster's Helm values

Existing buckets/roles on already-deployed clusters need to be imported into module state, not recreated.

## 3. Node-group security-group composition

A dedicated sandbox node group must carry the same set of security groups that the cluster's regular managed node groups carry — typically the EKS cluster SG **plus** the shared node SG. If the launch template only attaches the cluster SG, pods on sandbox nodes can't reach pods on the regular node group (DNS, in-cluster service calls, etc.) because the shared node SG's ingress is self-referential.

**Acceptance:** the Terraform launch template for the sandbox node group attaches both SGs by default, matching how EKS managed node groups normally provision.

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

1. `terraform apply` against the cluster (provisions bucket + role, sets metadata hop-limit).
2. Copy `role_arn` and `bucket_name` from terraform outputs into the cluster's Helm values alongside `ENABLE_CRAFT: "true"`.
3. `helm upgrade` (creates namespace, SA, network policy).

Item 5 is independent and bolts on to any cluster after the rest is in place.
