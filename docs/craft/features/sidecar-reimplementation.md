# Sidecar Reimplementation for Craft Sandboxes

Control-plane sidecar container that isolates credentials and privileged operations from the coding agent in the main sandbox container.

## Issues to Address

The single-container sandbox puts credentials and control-plane processes in the same container as the coding agent:

1. **S3/AWS credentials are accessible to the agent.** The pod's IRSA-bound service account injects `AWS_ROLE_ARN` and a projected token into the sandbox container.
2. **The push daemon runs in the agent's container** (port 8731).
3. **`ONYX_SANDBOX_PUSH_PUBLIC_KEY` is visible to the agent.**
4. **Snapshot operations run in the agent's container.** `create_snapshot` / `restore_snapshot` exec `aws s3 cp` inside the sandbox container.

## Important Notes

- Both containers use the same `onyxdotapp/sandbox` image with different `command` overrides.
- `eks.amazonaws.com/skip-containers: "sandbox"` on the service account skips IRSA injection into the `sandbox` container.
- Snapshot endpoints are Ed25519-signed.
- `GET /health` is the only unsigned endpoint.
- `shareProcessNamespace` is set to `false`.
- `/workspace/managed/` needs a new EmptyDir volume.
- ACP and all `kubectl exec` operations still target the `sandbox` container.
- `LocalSandboxManager` gets trivial implementations (no sidecar).

## Architecture

### Current (Single Container)

```
┌──────────────────────────────────────────────┐
│ Pod: sandbox-{id}                            │
│ SA: sandbox-file-sync (IRSA → S3)            │
│                                              │
│ ┌──────────────────────────────────────────┐ │
│ │ Container: sandbox                       │ │
│ │                                          │ │
│ │  - opencode agent                        │ │
│ │  - push daemon (:8731)                   │ │
│ │  - Next.js dev server                    │ │
│ │  - aws cli (snapshots)                   │ │
│ │                                          │ │
│ │  ENV: ONYX_PAT                           │ │
│ │  ENV: ONYX_SERVER_URL                    │ │
│ │  ENV: ONYX_SANDBOX_PUSH_PUBLIC_KEY       │ │
│ │  ENV: AWS_ROLE_ARN              ← IRSA   │ │
│ │  ENV: AWS_WEB_IDENTITY_TOKEN_FILE        │ │
│ └──────────────────────────────────────────┘ │
│                                              │
│ Volumes:                                     │
│   workspace → /workspace/sessions (EmptyDir) │
│   /workspace/managed/ is in container image  │
└──────────────────────────────────────────────┘
```

### Target (Two Containers, Single Image)

```
┌───────────────────────────────────────────────────────────────┐
│ Pod: sandbox-{id}                                             │
│ SA: sandbox-file-sync, skip-containers: "sandbox"             │
│ shareProcessNamespace: false                                  │
│                                                               │
│ ┌───────────────────────────┐ ┌─────────────────────────────┐ │
│ │ Container: sandbox        │ │ Container: sidecar          │ │
│ │                           │ │                             │ │
│ │  - opencode agent         │ │  - daemon (:8731)           │ │
│ │  - Next.js dev server     │ │    - push                   │ │
│ │                           │ │    - snapshot create/restore│ │
│ │                           │ │  - aws cli                  │ │
│ │  ENV: ONYX_PAT            │ │                             │ │
│ │  ENV: ONYX_SERVER_URL     │ │  ENV: ONYX_SANDBOX_PUSH_    │ │
│ │                           │ │       PUBLIC_KEY            │ │
│ │  (no IRSA injection)      │ │  ENV: AWS_ROLE_ARN ← IRSA  │ │
│ └─────────────┬─────────────┘ └──────────────┬──────────────┘ │
│               │                              │                │
│               └──────── shared volumes ──────┘                │
│                                                               │
│ Volumes:                                                      │
│   workspace → /workspace/sessions (EmptyDir 50Gi, both rw)   │
│   managed   → /workspace/managed  (5Gi, sidecar rw, agent ro)│
└───────────────────────────────────────────────────────────────┘

Same image: onyxdotapp/sandbox:v0.1.X
sandbox runs entrypoint.sh, sidecar runs sidecar-entrypoint.sh
```

### Communication Patterns

```
api-server ──POST :8731──→ sidecar (push, snapshot create/restore — all signed)
api-server ──k8s exec────→ sandbox (session setup, ACP messages, file ops)
```

## Implementation Strategy

### Phase 1: Volume Changes

Add a second EmptyDir volume for `/workspace/managed/`:

```python
volumes = [
    client.V1Volume(
        name="workspace",
        empty_dir=client.V1EmptyDirVolumeSource(size_limit="50Gi"),
    ),
    client.V1Volume(
        name="managed",
        empty_dir=client.V1EmptyDirVolumeSource(size_limit="5Gi"),
    ),
]
```

Mounts:

- `workspace` at `/workspace/sessions` — both containers rw
- `managed` at `/workspace/managed` — sidecar rw, sandbox ro

### Phase 2: IRSA Isolation

Add `skip-containers` to the `sandbox-file-sync` service account:

```yaml
annotations:
  eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/sandbox-s3-role
  eks.amazonaws.com/skip-containers: "sandbox"
```

### Phase 3: Sidecar Entrypoint and Server

Rename `entrypoint.sh` to `sidecar-entrypoint.sh`. Replace `entrypoint.sh` with:

```bash
#!/bin/bash
set -e
trap 'kill 0 2>/dev/null; exit' SIGTERM SIGINT
sleep infinity &
wait
```

Add snapshot endpoints to the existing daemon (`daemon/server.py`):

- `POST /push` (signature-verified) — existing
- `GET /health` (unsigned) — existing
- `POST /snapshot/create` (signature-verified) — new
- `POST /snapshot/restore` (signature-verified) — new

All on port 8731. Add `daemon/snapshot.py` for the snapshot logic. Snapshot operations shell out to `aws s3 cp`.

Snapshot signing format: `{timestamp}|{endpoint_path}|{sha256_of_request_body}`.

Dockerfile changes:

```dockerfile
COPY entrypoint.sh /workspace/entrypoint.sh
COPY sidecar-entrypoint.sh /workspace/sidecar-entrypoint.sh
```

**Snapshot endpoints:**

`POST /snapshot/create`

```json
Request: {
    "session_id": "uuid",
    "tenant_id": "string",
    "s3_bucket": "string",
    "snapshot_id": "uuid"
}
Response: {
    "status": "created" | "empty",
    "storage_path": "tenant/snapshots/session/snapshot.tar.gz",
    "size_bytes": 12345
}
```

`POST /snapshot/restore`

```json
Request: {
    "session_id": "uuid",
    "s3_bucket": "string",
    "storage_path": "tenant/snapshots/session/snapshot.tar.gz"
}
Response: {
    "status": "restored"
}
```

### Phase 4: Pod Spec Changes

Modify `_create_sandbox_pod()` in `kubernetes_sandbox_manager.py`.

**Add sidecar container:**

```python
sidecar_container = client.V1Container(
    name="sidecar",
    image=self._image,
    command=["/workspace/sidecar-entrypoint.sh"],
    ports=[
        client.V1ContainerPort(name="push-daemon", container_port=PUSH_DAEMON_PORT),
    ],
    env=[
        client.V1EnvVar(name=_PUSH_PUBLIC_KEY_ENV, value=push_public_key_b64),
    ],
    volume_mounts=[
        client.V1VolumeMount(name="workspace", mount_path="/workspace/sessions"),
        client.V1VolumeMount(name="managed", mount_path="/workspace/managed"),
    ],
    resources=client.V1ResourceRequirements(
        requests={"cpu": "100m", "memory": "256Mi"},
        limits={"cpu": "500m", "memory": "512Mi"},
    ),
    security_context=client.V1SecurityContext(
        allow_privilege_escalation=False,
        read_only_root_filesystem=False,
        privileged=False,
        capabilities=client.V1Capabilities(drop=["ALL"]),
    ),
    liveness_probe=client.V1Probe(
        http_get=client.V1HTTPGetAction(path="/health", port=PUSH_DAEMON_PORT),
        initial_delay_seconds=5,
        period_seconds=30,
    ),
    readiness_probe=client.V1Probe(
        http_get=client.V1HTTPGetAction(path="/health", port=PUSH_DAEMON_PORT),
        initial_delay_seconds=3,
        period_seconds=10,
    ),
)
```

**Modify main container:**

- Remove `push-daemon` port declaration
- Remove `ONYX_SANDBOX_PUSH_PUBLIC_KEY` env var
- Override command to use simplified entrypoint
- Add `managed` volume mount with `read_only=True`

**Pod spec:**

```python
pod_spec = client.V1PodSpec(
    containers=[sandbox_container, sidecar_container],
    share_process_namespace=False,
    ...
)
```

### Phase 5: Update `KubernetesSandboxManager`

| Method                     | Current                                    | After                                                  |
| -------------------------- | ------------------------------------------ | ------------------------------------------------------ |
| `write_files_to_sandbox()` | HTTP POST to pod_ip:8731                   | Unchanged                                              |
| `create_snapshot()`        | `k8s_stream` exec into `sandbox` container | HTTP POST to pod_ip:8731 `/snapshot/create` (signed)   |
| `restore_snapshot()`       | `k8s_stream` exec into `sandbox` container | HTTP POST to pod_ip:8731 `/snapshot/restore` (signed)  |
| `health_check()`           | `k8s_stream` exec via `ACPExecClient`      | HTTP GET pod_ip:8731 `/health`                         |

All other methods continue to exec into the `sandbox` container.

### Phase 6: Helm & Cloud Deployment Updates

#### 6a. Helm Chart (`deployment/helm/charts/onyx/`)

No changes needed.

#### 6b. Production — `cloud-deployment-yamls/danswer/`

**`serviceaccount/sandbox-file-sync-sa.yaml`** — add `skip-containers`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sandbox-file-sync
  namespace: onyx-sandboxes
  labels:
    app.kubernetes.io/name: sandbox-file-sync
    app.kubernetes.io/component: sandbox-execution
    app.kubernetes.io/part-of: onyx
    app.kubernetes.io/managed-by: ArgoCD
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::855178474906:role/SandboxFileSyncRole-onyx-cloud-craft
    eks.amazonaws.com/skip-containers: "sandbox"
automountServiceAccountToken: true
```


#### 6c. Dev — `cloud-deployment-yamls/customers/onyx/`

The `sandbox-file-sync` SA for craft-dev needs the same `skip-containers: "sandbox"` annotation.

#### Deployment Order

1. Build and push the new sandbox image (snapshot endpoints in daemon, new entrypoints)
2. Merge backend code changes (sidecar in pod spec, snapshot methods call sidecar HTTP API)
3. Deploy SA annotation + backend atomically
4. Verify on a new pod:
   - `kubectl exec -c sandbox` → `AWS_ROLE_ARN` is unset
   - `kubectl exec -c sandbox` → `/var/run/secrets/eks.amazonaws.com/` does not exist
   - `kubectl exec -c sandbox` → `ONYX_SANDBOX_PUSH_PUBLIC_KEY` is unset
   - `kubectl exec -c sidecar` → `AWS_ROLE_ARN` is set
   - Snapshot create/restore succeeds through the sidecar

## Residual Risks

- `ONYX_PAT` stays in the main container.
- The sidecar has full-bucket S3 access. Follow-up: per-tenant IAM scoping.

## Tests

**Unit tests** (`backend/tests/unit/`):

- Sidecar server endpoint routing (snapshot create/restore, push, health)
- Snapshot create produces correct tar and uploads to S3 (mock subprocess)
- Snapshot restore downloads and extracts correctly (mock S3)
- Unsigned requests to snapshot endpoints are rejected
- `GET /health` returns 200 without signature

**External dependency unit tests** (`backend/tests/external_dependency_unit/craft/`):

- `_create_sandbox_pod()` produces two containers with `share_process_namespace=False`
- Sidecar has correct env vars, both volume mounts, probes on port 8731
- Main container does not have `ONYX_SANDBOX_PUSH_PUBLIC_KEY`
- `create_snapshot()` / `restore_snapshot()` call sidecar HTTP API (mock httpx)
- `write_files_to_sandbox()` unchanged (same port)

**Integration tests** (`backend/tests/integration/tests/craft/`):

- Both containers start and pass readiness
- Push daemon reachable on sidecar
- Snapshot create/restore through sidecar API
- `sandbox` container has no `AWS_ROLE_ARN` env var
- End-to-end: provision → setup → message → snapshot → restore
