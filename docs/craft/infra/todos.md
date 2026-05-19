# Craft Infra TODOs

Things to codify so enabling Craft on a new cluster becomes "set `ENABLE_CRAFT=true` in values.yaml" instead of following a manual setup guide. Each item is independent — ship in any order.

## 1. Helm template: sandbox ServiceAccount

Render the sandbox-file-sync ServiceAccount via the Helm chart when `ENABLE_CRAFT=true`, including any IAM/workload-identity annotations required for S3 access. Source the role identifier from a configurable values block and mark it required so a misconfigured deploy fails fast.

This removes the need for manual `kubectl annotate` steps and per-cluster raw SA manifests.

## 2. Terraform module: sandbox object store + workload-identity role

A shared Terraform module that provisions the cloud-side prerequisites for Craft on a given cluster:

- Object-storage bucket for snapshots (with encryption + public-access block)
- IAM policy granting the SA read/write/delete/list on that bucket
- IAM role with a trust policy scoped to the sandbox namespace + SA via the cluster's OIDC provider
- Outputs (`role_arn`, `bucket_name`) to wire into the cluster's Helm values

Existing buckets/roles on already-deployed clusters need to be imported into module state, not recreated.

## 3. Node-group metadata-service hardening

Enforce IMDSv2 with hop-limit 1 on the sandbox node group via Terraform so containers can't reach the instance metadata service. If a cluster's node group is currently managed outside Terraform, converting it is a prerequisite.

**Acceptance:** from inside any sandbox pod, a curl to the metadata service times out.

## 4. Network firewall (defense-in-depth)

Replicate the production network-firewall setup in every region that runs Craft. The firewall should:

- Block egress from sandbox subnets to RFC1918 ranges (lateral movement)
- Block egress to the instance metadata service (belt-and-suspenders with item 3)
- Subscribe to a managed threat-intelligence rule group
- Sit in dedicated firewall subnets with sandbox-subnet route tables pointing `0.0.0.0/0` at the firewall endpoint

**Acceptance:** from inside a sandbox pod, RFC1918 + metadata-service requests fail; normal outbound HTTPS to LLM providers still works.

---

## When items 1–3 land

Onboarding a new Craft cluster becomes:

1. `terraform apply` against the cluster (provisions bucket + role, sets metadata hop-limit).
2. Copy `role_arn` and `bucket_name` from terraform outputs into the cluster's Helm values alongside `ENABLE_CRAFT: "true"`.
3. `helm upgrade` (creates namespace, SA, network policy).

Item 4 is independent and bolts on to any cluster after the rest is in place.
