# Onyx Craft on EKS: infrastructure and migration runbook

How to stand up Onyx + Craft on EKS, and how to migrate older Craft clusters
onto the current Helm/Terraform contract.

## 0. Ownership boundary

Terraform owns AWS infrastructure:

- VPC, EKS, node groups, EKS add-ons, storage classes.
- Managed data stores: RDS, ElastiCache, OpenSearch, and the main Onyx
  FileStore bucket.
- Workload identity for Onyx application pods, when using IRSA instead of
  static S3 credentials.

Helm owns Kubernetes objects:

- Onyx workloads, sandbox proxy, ConfigMaps, and Secrets.
- `Namespace/onyx-sandboxes`.
- `ServiceAccount/sandbox` in `onyx-sandboxes`.
- Sandbox manager RBAC and proxy service lookup RBAC.

Craft snapshots do not have an independent object store. The sandbox sidecar
only packages and restores pod-local files. The API server persists snapshot
archives through `SnapshotManager(get_default_file_store())`, so snapshots use
the same `FILE_STORE_BACKEND`, bucket, credentials, and metadata records as the
rest of Onyx FileStore.

## 1. What Craft adds

Each Craft sandbox is a pod in `onyx-sandboxes` with:

- a `sandbox` container running the agent/code environment;
- a `sidecar` container running the push daemon and snapshot filesystem API;
- a shared `emptyDir` mounted at `/workspace/sessions`;
- a ConfigMap-backed proxy CA bundle;
- `serviceAccountName: sandbox`;
- `automountServiceAccountToken: false` on the ServiceAccount;
- `nodeSelector: onyx.app/workload=sandbox`;
- a matching `workload=sandbox:NoSchedule` toleration.

The sandbox manager also creates a per-sandbox ClusterIP Service for opencode,
the push daemon, and Next.js dev-server ports, plus a per-sandbox Secret for
opencode auth/config.

## 2. Required values

For an EKS deployment with external AWS services, point the normal chart values
at the Terraform outputs:

- Disable in-cluster dependencies as appropriate:
  `postgresql.enabled=false`, `redis.enabled=false`, `opensearch.enabled=false`,
  `minio.enabled=false`.
- FileStore: set `configMap.FILE_STORE_BACKEND=s3`,
  `configMap.S3_FILE_STORE_BUCKET_NAME=<main-file-store-bucket>`,
  `configMap.S3_ENDPOINT_URL=""`, and `configMap.AWS_REGION_NAME=<region>`.
- Craft: set `configMap.ENABLE_CRAFT=true`,
  `configMap.SANDBOX_BACKEND=kubernetes`,
  `configMap.SANDBOX_API_SERVER_URL=https://<your-onyx-host>`, and enable
  `auth.sandboxPushSecret`.
- RBAC: use `craft.extraBoundServiceAccounts` only when extra release-namespace
  ServiceAccounts besides the main Onyx workload SA need to manage sandbox pods.

Do not set `SANDBOX_S3_BUCKET`; it is no longer read. Do not create a Craft
snapshot bucket or sandbox file-sync IRSA role.

Example install shape:

```bash
cd deployment/terraform/<root>
terraform init && terraform apply

aws eks update-kubeconfig --name "$(terraform output -raw cluster_name)" --region <region>

cd ../../helm/charts/onyx
helm dependency build
helm upgrade --install onyx . -n onyx -f <values> \
  --set auth.postgresql.values.password=<rds pw> \
  --set auth.userauth.values.user_auth_secret="$(openssl rand -hex 32)" \
  --set configMap.S3_FILE_STORE_BUCKET_NAME="$(terraform -chdir=<root> output -raw file_store_bucket_name)" \
  --set auth.sandboxPushSecret.values.private_key="$(<gen ed25519 raw seed b64>)"
```

## 3. Sandbox node group

Craft does not require a special Terraform module beyond the normal EKS node
group inputs, but sandbox pods need nodes that satisfy the scheduling contract:

```yaml
labels:
  onyx.app/workload: sandbox
taints:
  - key: workload
    value: sandbox
    effect: NO_SCHEDULE
```

The sandbox manager schedules every sandbox pod with the matching selector and
toleration. Dedicated sandbox nodes are strongly recommended so user code runs
away from application workloads and can be routed through stricter network
controls.

## 4. Migrating older Craft/EKS setups

Older clusters may have:

- a separate sandbox snapshot bucket;
- a `sandbox-file-sync` ServiceAccount;
- an IRSA role such as `SandboxFileSyncRole-*`;
- Helm values for `SANDBOX_S3_BUCKET` or `craft.sandboxFileSyncRoleArn`.

Current code does not use those resources. For a new cloud deploy:

1. Remove `SANDBOX_S3_BUCKET` from values and ConfigMaps.
2. Remove `craft.sandboxFileSyncRoleArn` from Helm values.
3. Set `SANDBOX_SERVICE_ACCOUNT_NAME=sandbox`, or omit it and use the chart
   default.
4. Let Helm render `templates/sandbox-rbac.yaml`; it creates
   `ServiceAccount/sandbox` without IRSA annotations.
5. Ensure the API server and Celery workers that create/restore snapshots have
   normal Onyx FileStore access.
6. Delete or stop managing the old `sandbox-file-sync` ServiceAccount after no
   running sandbox pods reference it.

Existing snapshot rows created by the old implementation point at raw keys in
the old sandbox bucket and do not have FileStore metadata. Backwards
compatibility is intentionally not provided. If a specific old session must be
kept, migrate it by reading the old object and saving it through FileStore with
`FileOrigin.SANDBOX_SNAPSHOT`; copying objects into the main bucket is not
enough because FileStore reads by `file_record`.

## 5. Post-deploy checks

```bash
# Helm renders the sandbox namespace and RBAC.
helm template onyx deployment/helm/charts/onyx -n onyx -f your-values.yaml \
  --show-only templates/sandbox-namespace.yaml
helm template onyx deployment/helm/charts/onyx -n onyx -f your-values.yaml \
  --show-only templates/sandbox-rbac.yaml

# Workload SA can manage sandboxes.
kubectl auth can-i create pods -n onyx-sandboxes \
  --as system:serviceaccount:onyx:onyx-workload-access
kubectl auth can-i create pods/exec -n onyx-sandboxes \
  --as system:serviceaccount:onyx:onyx-workload-access
kubectl auth can-i get services -n onyx \
  --as system:serviceaccount:onyx:onyx-workload-access

# Sandbox SA exists and has no IRSA annotation.
kubectl -n onyx-sandboxes get sa sandbox -o yaml

# Sandbox nodes exist if using dedicated scheduling.
kubectl get nodes -l onyx.app/workload=sandbox
```

End-to-end validation should cover: create a Craft session, write files under
`outputs/` and `attachments/`, idle/snapshot it, terminate the sandbox pod, then
revive the session and confirm the files restore from the main Onyx FileStore.
