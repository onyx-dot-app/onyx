# Kubernetes Sandbox Module Plan

This document outlines the implementation strategy for a Kubernetes-native sandbox system where each sandbox runs as an independent Kubernetes Pod.

## Issues to Address

1. **Pod-Based Sandbox Execution**: Replace the current filesystem/subprocess-based sandbox system with Kubernetes-native pods for true container isolation
2. **Dynamic Pod Lifecycle Management**: Create, monitor, and terminate sandbox pods on-demand through the Kubernetes API
3. **Network Routing**: Enable access to sandbox Next.js servers from both the API server and external users via Ingress
4. **State Persistence**: Handle pod ephemerality through S3 snapshots (no PVCs)
5. **Helm Chart Integration**: Provide configurable Helm templates for the sandbox system
6. **Multi-Tenant Isolation**: Ensure tenant separation through Kubernetes namespaces or label-based isolation

## Important Notes

### Current Architecture Understanding

- **LocalSandboxManager** (`sandbox/manager.py`) uses filesystem directories and subprocesses
- Agent communication uses ACP (Agent Client Protocol) - JSON-RPC 2.0 over stdin/stdout for subprocesses
- Next.js servers run on dynamically allocated ports (3010-3100 range)
- Snapshots store `outputs/` directory to S3-compatible storage when `SANDBOX_BACKEND=kubernetes`
- Session management is tied to the Sandbox model via `session_id` foreign key

### Kubernetes-Native Benefits Over DooD

The existing plans mention Docker-out-of-Docker (DooD), but a Kubernetes-native approach is superior:

| Aspect | DooD Approach | Kubernetes-Native (This Plan) |
|--------|--------------|-------------------------------|
| Node Affinity | Required (must access Docker socket) | Not required (pods scheduled anywhere) |
| Security | Requires privileged access to Docker socket | Standard Kubernetes RBAC |
| Scaling | Limited by single node's Docker daemon | Cluster-wide scaling |
| Networking | Custom Docker networks | Native Kubernetes networking |
| Resource Management | Docker resource limits | Kubernetes ResourceQuotas & LimitRanges |
| Health Checks | Custom implementation | Native Kubernetes probes |

### Key Constraints

1. **Pod Startup Latency**: Kubernetes pods take 10-30s to become ready (image pull, container start, S3 sync, Next.js build)
2. **Service Discovery**: Each sandbox needs a predictable service endpoint for HTTP communication
3. **Ingress Routing**: Dynamic subpath or subdomain routing to sandbox pods
4. **S3 Access for Init Container**: Init container needs S3 access for snapshot restore and knowledge file sync
5. **RBAC Requirements**: API server needs permissions to create/delete pods, services, configmaps

### Security Model (EKS)

Sandboxes execute untrusted code. We must prevent access to:

1. **Network access** to private IP space (VPC, peered networks, RFC1918, metadata services)
2. **AWS API access** via stolen credentials (IMDS, node role, service account tokens)

The security architecture uses defense-in-depth with multiple layers:

| Layer | What it Blocks | Bypass Risk |
|-------|---------------|-------------|
| **AWS Network Firewall** | All RFC1918, IMDS, link-local at VPC edge | Very low |
| **NACL** | IMDS (backup) | Very low |
| **IMDSv2 + Hop=1** | Container IMDS access | Low |
| **Minimal Node IAM** | AWS API abuse if creds stolen | Medium (limits blast radius) |
| **No IRSA** | Direct AWS API access from pod | None (no creds to steal) |
| **NetworkPolicy** | Defense in depth (CNI-level) | Medium (CNI bugs) |
| **Pod Security Standards** | Privilege escalation | Low |
| **Node Isolation** | Lateral movement to other workloads | Low |

## Implementation Strategy

### Phase 1: Core Infrastructure

#### 1.1 KubernetesSandboxManager

Create `backend/onyx/server/features/build/sandbox/kubernetes_manager.py`:

```
KubernetesSandboxManager
├── provision(session_id, tenant_id, ...)
│   ├── Create ConfigMap for AGENTS.md
│   ├── Create Pod with sandbox container (includes init container for S3 sync)
│   ├── Create Service for pod
│   └── Wait for pod ready + update DB
├── terminate(sandbox_id)
│   ├── Create snapshot to S3 (if enabled)
│   ├── Delete Service
│   ├── Delete Pod
│   ├── Delete ConfigMap
│   └── Update DB status
├── get_agent_client(sandbox_id) → ACPHttpClient
├── get_sandbox_url(sandbox_id) → str
└── health_check(sandbox_id) → HealthStatus
```

**Dependencies**:
- `kubernetes` Python client library (add to requirements)
- Service account with appropriate RBAC permissions

#### 1.2 Sandbox Pod Specification

Each sandbox pod contains an init container for S3 sync and the main sandbox container. All storage uses `emptyDir` volumes (ephemeral, cleaned up with pod).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sandbox-{session_id_short}
  namespace: onyx-sandboxes
  labels:
    app.kubernetes.io/component: sandbox
    onyx.app/session-id: {session_id}
    onyx.app/tenant-id: {tenant_id}
spec:
  serviceAccountName: sandbox-file-sync  # Has IRSA for S3 access (init container only)

  initContainers:
    - name: file-sync
      image: amazon/aws-cli:latest
      env:
        - name: SESSION_ID
          value: {session_id}
        - name: TENANT_ID
          value: {tenant_id}
        - name: SNAPSHOT_ID
          value: {snapshot_id}  # Empty if new sandbox
        - name: S3_BUCKET
          value: {SANDBOX_S3_BUCKET}
      command:
        - /bin/sh
        - -c
        - |
          set -e

          # Restore from snapshot if provided
          if [ -n "$SNAPSHOT_ID" ]; then
            echo "Restoring from snapshot: $SNAPSHOT_ID"
            aws s3 cp "s3://$S3_BUCKET/$TENANT_ID/snapshots/$SESSION_ID/$SNAPSHOT_ID.tar.gz" /tmp/snapshot.tar.gz
            tar -xzf /tmp/snapshot.tar.gz -C /workspace/outputs
            rm /tmp/snapshot.tar.gz
          fi

          # Sync knowledge files for this user/tenant
          echo "Syncing knowledge files for tenant: $TENANT_ID / $USER_ID"
          aws s3 sync "s3://$S3_BUCKET/$TENANT_ID/knowledge/$USER_ID/" /workspace/files/ --quiet || true

          # Sync user-uploaded files for this session
          echo "Syncing user uploads for session: $SESSION_ID"
          aws s3 sync "s3://$S3_BUCKET/$TENANT_ID/uploads/$SESSION_ID/" /workspace/user_uploaded_files/ --quiet || true

          echo "File sync complete"
      volumeMounts:
        - name: outputs
          mountPath: /workspace/outputs
        - name: files
          mountPath: /workspace/files
        - name: user-uploads
          mountPath: /workspace/user_uploaded_files
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
        limits:
          cpu: 1000m
          memory: 1Gi

  containers:
    - name: sandbox
      image: {SANDBOX_CONTAINER_IMAGE}
      ports:
        - name: nextjs
          containerPort: 3000
        - name: agent
          containerPort: 8081
      env:
        - name: SESSION_ID
          value: {session_id}
        - name: LLM_PROVIDER_CONFIG
          valueFrom:
            secretKeyRef: ...
      volumeMounts:
        - name: outputs
          mountPath: /workspace/outputs
        - name: files
          mountPath: /workspace/files
          readOnly: true
        - name: user-uploads
          mountPath: /workspace/user_uploaded_files
          readOnly: true
        - name: instructions
          mountPath: /workspace/instructions
          readOnly: true
      resources:
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: 2000m
          memory: 4Gi
      readinessProbe:
        httpGet:
          path: /
          port: 3000
        initialDelaySeconds: 10
        periodSeconds: 5
      livenessProbe:
        httpGet:
          path: /api/health
          port: 8081
        initialDelaySeconds: 30
        periodSeconds: 30

  volumes:
    - name: outputs
      emptyDir:
        sizeLimit: 5Gi
    - name: files
      emptyDir:
        sizeLimit: 1Gi
    - name: user-uploads
      emptyDir:
        sizeLimit: 1Gi
    - name: instructions
      configMap:
        name: sandbox-instructions-{session_id_short}

  restartPolicy: Never  # Don't restart failed sandboxes
  terminationGracePeriodSeconds: 30
```

**Note on S3 Access**: The init container uses IRSA (IAM Roles for Service Accounts) to access S3. This is safe because:
1. The init container runs and completes **before** the sandbox container starts
2. The sandbox container does **not** have the IRSA service account token mounted
3. The sandbox container has no AWS credentials

#### 1.3 Sandbox Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: sandbox-{session_id_short}
  namespace: {namespace}
  labels:
    onyx.app/session-id: {session_id}
spec:
  type: ClusterIP
  selector:
    onyx.app/session-id: {session_id}
  ports:
    - name: nextjs
      port: 3000
      targetPort: 3000
    - name: agent
      port: 8081
      targetPort: 8081
```

#### 1.4 Sandbox Container Image

Create a new Docker image at `backend/onyx/server/features/build/sandbox/docker/Dockerfile`:

```dockerfile
FROM node:20-slim

# Install dependencies for opencode
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv curl git \
    && rm -rf /var/lib/apt/lists/*

# Install opencode CLI
RUN curl -fsSL https://opencode.ai/install.sh | bash

# Copy Next.js template
COPY outputs-template /workspace/outputs
WORKDIR /workspace/outputs/web

# Pre-install npm dependencies
RUN npm ci

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 3000 8081
ENTRYPOINT ["/entrypoint.sh"]
```

**Entrypoint Script** (`entrypoint.sh`):
```bash
#!/bin/bash
set -e

# Start Next.js dev server in background
cd /workspace/outputs/web
npm run dev &
NEXTJS_PID=$!

# Start opencode ACP server
cd /workspace
opencode serve --port 8081 --cwd /workspace/outputs &
AGENT_PID=$!

# Wait for either process to exit
wait -n $NEXTJS_PID $AGENT_PID
```

### Phase 2: Manager Implementation

#### 2.1 Abstract Manager Interface Update

Update `backend/onyx/server/features/build/sandbox/manager.py`:

```python
class SandboxManager(ABC):
    """Abstract interface for sandbox lifecycle management."""

    @abstractmethod
    def provision(
        self,
        session_id: UUID,
        tenant_id: str,
        user_id: UUID,
        knowledge_path: str,
        llm_config: dict,
    ) -> Sandbox:
        """Provision a new sandbox environment."""
        pass

    @abstractmethod
    def terminate(self, sandbox_id: UUID, create_snapshot: bool = True) -> None:
        """Terminate a sandbox and optionally create a snapshot."""
        pass

    @abstractmethod
    def get_agent_client(self, sandbox_id: UUID) -> ACPClient:
        """Get an ACP client for communicating with the sandbox agent."""
        pass

    @abstractmethod
    def get_nextjs_url(self, sandbox_id: UUID) -> str:
        """Get the URL for the sandbox's Next.js server."""
        pass

    @abstractmethod
    def restore_from_snapshot(
        self,
        session_id: UUID,
        snapshot_id: UUID,
    ) -> Sandbox:
        """Restore a sandbox from a snapshot."""
        pass


def get_sandbox_manager() -> SandboxManager:
    """Factory function to get the appropriate sandbox manager."""
    backend = os.getenv("SANDBOX_BACKEND", "local")
    if backend == "kubernetes":
        from onyx.server.features.build.sandbox.kubernetes_manager import KubernetesSandboxManager
        return KubernetesSandboxManager()
    else:
        return LocalSandboxManager()
```

#### 2.2 KubernetesSandboxManager Implementation

New file: `backend/onyx/server/features/build/sandbox/kubernetes_manager.py`

Key methods:

```python
class KubernetesSandboxManager(SandboxManager):
    def __init__(self):
        # Load Kubernetes config (in-cluster or kubeconfig)
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._core_api = client.CoreV1Api()
        self._batch_api = client.BatchV1Api()
        self._namespace = os.getenv("SANDBOX_NAMESPACE", "onyx-sandboxes")
        self._image = os.getenv("SANDBOX_CONTAINER_IMAGE", "onyxdotapp/sandbox:latest")
        self._s3_bucket = os.getenv("SANDBOX_S3_BUCKET")

    def provision(self, ...) -> Sandbox:
        session_id_short = str(session_id)[:8]

        # 1. Create instructions ConfigMap
        configmap = self._create_instructions_configmap(session_id, session_id_short)
        self._core_api.create_namespaced_config_map(
            namespace=self._namespace,
            body=configmap
        )

        # 2. Create sandbox Pod (init container handles S3 sync for snapshots/files)
        pod = self._create_sandbox_pod(
            session_id=session_id,
            session_id_short=session_id_short,
            tenant_id=tenant_id,
            llm_config=llm_config,
            snapshot_id=snapshot_id,  # Passed to init container for restore
        )
        self._core_api.create_namespaced_pod(
            namespace=self._namespace,
            body=pod
        )

        # 3. Create Service
        service = self._create_sandbox_service(session_id, session_id_short)
        self._core_api.create_namespaced_service(
            namespace=self._namespace,
            body=service
        )

        # 4. Wait for pod to be ready
        self._wait_for_pod_ready(session_id_short)

        # 5. Create DB record
        sandbox = create_sandbox(
            db_session=db_session,
            session_id=session_id,
            container_id=f"sandbox-{session_id_short}",  # Pod name
            status=SandboxStatus.RUNNING,
            nextjs_port=3000,  # Always 3000 within cluster
        )

        return sandbox

    def terminate(self, sandbox_id: UUID, create_snapshot: bool = True) -> None:
        sandbox = get_sandbox(db_session, sandbox_id)
        pod_name = sandbox.container_id
        session_id_short = pod_name.replace("sandbox-", "")

        # 1. Create snapshot to S3 before deletion if requested
        # This uses a Job to tar the outputs directory and stream to S3
        if create_snapshot:
            self._create_snapshot_to_s3(sandbox)

        # 2. Delete resources (reverse order of creation)
        self._core_api.delete_namespaced_service(
            name=pod_name,
            namespace=self._namespace
        )

        self._core_api.delete_namespaced_pod(
            name=pod_name,
            namespace=self._namespace
        )

        # 3. Delete ConfigMap
        self._core_api.delete_namespaced_config_map(
            name=f"sandbox-instructions-{session_id_short}",
            namespace=self._namespace
        )

        # 4. Update DB
        update_sandbox_status(db_session, sandbox_id, SandboxStatus.TERMINATED)

    def _create_snapshot_to_s3(self, sandbox: Sandbox) -> str:
        """Create a snapshot by running a Job that tars outputs and streams to S3."""
        snapshot_id = str(uuid4())
        pod_name = sandbox.container_id
        session = get_session_by_sandbox(db_session, sandbox.id)

        # Use a Job to tar outputs and pipe to aws s3 cp
        # This avoids needing to copy data through the API server
        # Include --tagging for S3 lifecycle expiration
        s3_path = f's3://{self._s3_bucket}/{session.tenant_id}/snapshots/{session.id}/{snapshot_id}.tar.gz'
        exec_command = [
            '/bin/sh', '-c',
            f'tar -czf - -C /workspace outputs | '
            f'aws s3 cp - {s3_path} --tagging "Type=snapshot"'
        ]

        # Execute via a short-lived Job with the file-sync service account (has S3 access)
        self._run_snapshot_job(sandbox, snapshot_id, exec_command)

        return snapshot_id

    def get_nextjs_url(self, sandbox_id: UUID) -> str:
        """Return the internal cluster URL for the sandbox's Next.js server."""
        sandbox = get_sandbox(db_session, sandbox_id)
        pod_name = sandbox.container_id
        return f"http://{pod_name}.{self._namespace}.svc.cluster.local:3000"

    def get_agent_client(self, sandbox_id: UUID) -> ACPHttpClient:
        """Return an HTTP-based ACP client for the sandbox agent."""
        sandbox = get_sandbox(db_session, sandbox_id)
        pod_name = sandbox.container_id
        agent_url = f"http://{pod_name}.{self._namespace}.svc.cluster.local:8081"
        return ACPHttpClient(agent_url)
```

#### 2.3 ACP HTTP Client

New file: `backend/onyx/server/features/build/sandbox/internal/acp_http_client.py`

```python
class ACPHttpClient:
    """HTTP-based ACP client for communicating with sandbox agents in pods."""

    def __init__(self, base_url: str):
        self._base_url = base_url
        self._http_client = httpx.Client(timeout=300.0)
        self._session_id: str | None = None

    def initialize(self) -> str:
        """Initialize ACP session and return session ID."""
        response = self._http_client.post(
            f"{self._base_url}/acp/initialize",
            json={"client_info": {"name": "onyx", "version": "1.0"}}
        )
        data = response.json()

        # Create session
        session_response = self._http_client.post(
            f"{self._base_url}/acp/session/new"
        )
        self._session_id = session_response.json()["session_id"]
        return self._session_id

    def send_message(self, content: str) -> Generator[ACPEvent, None, None]:
        """Send a message and stream ACP events."""
        with self._http_client.stream(
            "POST",
            f"{self._base_url}/acp/session/{self._session_id}/prompt",
            json={"content": content}
        ) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event_data = json.loads(line[6:])
                    yield parse_acp_event(event_data)

    def cancel(self) -> None:
        """Cancel the current operation."""
        self._http_client.post(
            f"{self._base_url}/acp/session/{self._session_id}/cancel"
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._http_client.close()
```

### Phase 3: Ingress & Routing

#### 3.1 Dynamic Ingress for Sandbox Access

Two options for external sandbox access:

**Option A: Wildcard Subdomain** (Recommended)
```yaml
# Ingress per sandbox (created dynamically)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sandbox-{session_id_short}
  namespace: {namespace}
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /$2
spec:
  ingressClassName: nginx
  rules:
    - host: sandbox-{session_id_short}.{domain}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: sandbox-{session_id_short}
                port:
                  number: 3000
```

**Option B: Path-Based Routing**
```yaml
# Single ingress with path prefix
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sandbox-router
  annotations:
    nginx.ingress.kubernetes.io/use-regex: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /$2
spec:
  rules:
    - host: {domain}
      http:
        paths:
          - path: /sandbox/([^/]+)(/.*)?
            pathType: ImplementationSpecific
            backend:
              service:
                name: sandbox-router  # Routes to correct sandbox
                port:
                  number: 80
```

#### 3.2 Webapp Proxy Updates

Update the existing `_get_sandbox_url()` function in `backend/onyx/server/features/build/api/api.py` to delegate URL resolution to the sandbox manager:

```python
def _get_sandbox_url(session_id: UUID, db_session: Session) -> str:
    """Get the base URL for a sandbox's Next.js server."""
    sandbox = get_sandbox_by_session(db_session, session_id)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if sandbox.status != SandboxStatus.RUNNING:
        raise HTTPException(status_code=503, detail="Sandbox not running")

    # Delegate to sandbox manager for URL resolution
    # - Local: returns http://localhost:{port}
    # - Kubernetes: returns http://sandbox-{id}.{namespace}.svc.cluster.local:3000
    manager = get_sandbox_manager()
    return manager.get_nextjs_url_sync(sandbox)
```

Add `get_nextjs_url_sync()` to the `SandboxManager` interface (synchronous version for use in sync endpoints).

### Phase 4: Helm Chart Integration

#### 4.1 New Values Configuration

Add to `deployment/helm/charts/onyx/values.yaml`:

```yaml
sandbox:
  enabled: false  # Disabled by default

  # Namespace for sandbox pods
  namespace: onyx-sandboxes
  createNamespace: true

  # Container image (pulled from ECR via pull-through cache)
  image:
    repository: onyxdotapp/sandbox
    tag: ""  # Uses global.version if empty
    pullPolicy: IfNotPresent

  # Resource limits per sandbox pod
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 4Gi

  # S3 configuration for file sync (snapshots, knowledge files, user uploads)
  s3:
    bucket: ""  # Required: S3 bucket for sandbox files
    irsaRoleArn: ""  # Required: IAM role ARN for init container S3 access
    # S3 path structure (tenant_id as top-level prefix for easy isolation):
    #   s3://{bucket}/{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz
    #   s3://{bucket}/{tenant_id}/knowledge/{user_id}/
    #   s3://{bucket}/{tenant_id}/uploads/{session_id}/

  # emptyDir size limits (ephemeral storage, cleaned up with pod)
  ephemeralStorage:
    outputsLimit: 5Gi
    filesLimit: 1Gi
    uploadsLimit: 1Gi

  # Scaling limits
  maxConcurrentPerTenant: 10
  maxConcurrentTotal: 100

  # Idle timeout (seconds before pod termination)
  idleTimeoutSeconds: 900

  # Snapshot configuration
  snapshots:
    enabled: true
    retentionDays: 30

  # Networking
  ingress:
    enabled: true
    className: nginx
    # Option 1: Wildcard subdomain
    wildcardDomain: ""  # e.g., "*.sandbox.example.com"
    # Option 2: Path-based (used if wildcardDomain is empty)
    basePath: /sandbox

  # RBAC (for API server to manage sandbox pods)
  rbac:
    create: true

  # Service account for sandbox pods (NO IRSA - no AWS API access)
  serviceAccount:
    create: true
    name: sandbox-runner
    annotations: {}
    # NOTE: Do NOT add eks.amazonaws.com/role-arn annotation
    # Sandbox pods must have zero AWS API access

  # Pod security context
  podSecurityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault

  # Container security context
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: false
    privileged: false
    capabilities:
      drop:
        - ALL

  # Explicitly disable host access
  hostNetwork: false
  hostPID: false
  hostIPC: false

  # Node selection - schedule ONLY on dedicated sandbox nodes
  # These must match the taints/labels on the sandbox node group
  nodeSelector:
    onyx.app/workload: sandbox

  tolerations:
    - key: "workload"
      operator: "Equal"
      value: "sandbox"
      effect: "NoSchedule"

  affinity: {}

  # Network policy configuration
  networkPolicy:
    enabled: true
    # Allow DNS only to kube-dns
    dnsPolicy: "ClusterFirst"
```

#### 4.2 RBAC Templates

New file: `deployment/helm/charts/onyx/templates/sandbox-rbac.yaml`

```yaml
{{- if .Values.sandbox.enabled }}
{{- if .Values.sandbox.rbac.create }}
---
# Service account for API server to manage sandbox pods
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "onyx.fullname" . }}-sandbox-manager
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
    app.kubernetes.io/component: sandbox-manager
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "onyx.fullname" . }}-sandbox-manager
  namespace: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["create", "delete", "get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]  # For snapshot creation
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["create", "delete", "get", "list"]
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["create", "delete", "get", "list"]
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["create", "delete", "get", "list"]  # For snapshot jobs
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["create", "delete", "get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "onyx.fullname" . }}-sandbox-manager
  namespace: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ include "onyx.fullname" . }}-sandbox-manager
subjects:
  - kind: ServiceAccount
    name: {{ include "onyx.fullname" . }}-sandbox-manager
    namespace: {{ .Release.Namespace }}
---
# Service account for sandbox pods' init container (S3 access via IRSA)
# NOTE: This SA has IRSA annotation for S3 access - used ONLY by init container
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sandbox-file-sync
  namespace: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
    app.kubernetes.io/component: sandbox-file-sync
  annotations:
    # IRSA annotation - the IAM role must have S3 read/write access to the sandbox bucket
    eks.amazonaws.com/role-arn: {{ .Values.sandbox.s3.irsaRoleArn | quote }}
{{- end }}
{{- end }}
```

#### 4.3 Namespace Template

New file: `deployment/helm/charts/onyx/templates/sandbox-namespace.yaml`

```yaml
{{- if .Values.sandbox.enabled }}
{{- if .Values.sandbox.createNamespace }}
apiVersion: v1
kind: Namespace
metadata:
  name: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
    app.kubernetes.io/component: sandbox
    # Pod Security Standards - enforce restricted profile
    # This is a cluster-level enforcement that prevents privilege escalation
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
{{- end }}
{{- end }}
```

#### 4.4 LimitRange Template (Resource Defaults)

New file: `deployment/helm/charts/onyx/templates/sandbox-limitrange.yaml`

```yaml
{{- if .Values.sandbox.enabled }}
apiVersion: v1
kind: LimitRange
metadata:
  name: sandbox-limits
  namespace: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
spec:
  limits:
    - default:
        cpu: {{ .Values.sandbox.resources.limits.cpu }}
        memory: {{ .Values.sandbox.resources.limits.memory }}
      defaultRequest:
        cpu: {{ .Values.sandbox.resources.requests.cpu }}
        memory: {{ .Values.sandbox.resources.requests.memory }}
      type: Container
{{- end }}
```

#### 4.5 ResourceQuota Template (Total Cluster Limits)

New file: `deployment/helm/charts/onyx/templates/sandbox-resourcequota.yaml`

```yaml
{{- if .Values.sandbox.enabled }}
apiVersion: v1
kind: ResourceQuota
metadata:
  name: sandbox-quota
  namespace: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
spec:
  hard:
    pods: "{{ .Values.sandbox.maxConcurrentTotal }}"
    requests.cpu: "{{ mul .Values.sandbox.maxConcurrentTotal 500 }}m"
    requests.memory: "{{ mul .Values.sandbox.maxConcurrentTotal 1 }}Gi"
    limits.cpu: "{{ mul .Values.sandbox.maxConcurrentTotal 2 }}"
    limits.memory: "{{ mul .Values.sandbox.maxConcurrentTotal 4 }}Gi"
{{- end }}
```

#### 4.6 Network Policy Template

New file: `deployment/helm/charts/onyx/templates/sandbox-networkpolicy.yaml`

This is a **defense-in-depth** layer. The primary network isolation is enforced by AWS Network Firewall (see Phase 6), but NetworkPolicies provide an additional safety net at the CNI level.

```yaml
{{- if .Values.sandbox.enabled }}
{{- if .Values.sandbox.networkPolicy.enabled }}
---
# Default deny all traffic for sandbox pods
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-default-deny
  namespace: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: sandbox
  policyTypes:
    - Egress
    - Ingress
  # No rules = deny all (explicit baseline)
---
# Allow only required traffic
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-allow-required
  namespace: {{ .Values.sandbox.namespace }}
  labels:
    {{- include "onyx.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: sandbox
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow traffic from API server namespace only
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ .Release.Namespace }}
      ports:
        - protocol: TCP
          port: 3000
        - protocol: TCP
          port: 8081
    # Allow traffic from ingress controller
    - from:
        - namespaceSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - protocol: TCP
          port: 3000
  egress:
    # DNS to kube-dns only (not arbitrary DNS servers)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # HTTPS to external only - block all private ranges
    # NOTE: AWS Network Firewall is the primary enforcer; this is defense-in-depth
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8        # RFC1918 Class A
              - 172.16.0.0/12     # RFC1918 Class B
              - 192.168.0.0/16    # RFC1918 Class C
              - 169.254.0.0/16    # Link-local (includes IMDS)
              - 100.64.0.0/10     # CGNAT
              - 127.0.0.0/8       # Loopback
      ports:
        - protocol: TCP
          port: 443
    # Allow to API server for file uploads/downloads
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ .Release.Namespace }}
      ports:
        - protocol: TCP
          port: 8080
{{- end }}
{{- end }}
```

**Important**: NetworkPolicies require a CNI that enforces them. AWS VPC CNI alone does **not** enforce NetworkPolicies. You must also deploy one of:
- **AWS Network Policy Controller** (native VPC CNI add-on)
- **Calico** (popular, battle-tested)
- **Cilium** (eBPF-based, high performance)

#### 4.7 ConfigMap Updates

Add to `deployment/helm/charts/onyx/templates/configmap.yaml`:

```yaml
{{- if .Values.sandbox.enabled }}
  # Sandbox configuration
  SANDBOX_BACKEND: "kubernetes"
  SANDBOX_NAMESPACE: {{ .Values.sandbox.namespace | quote }}
  SANDBOX_CONTAINER_IMAGE: "{{ .Values.sandbox.image.repository }}:{{ .Values.sandbox.image.tag | default .Values.global.version }}"
  SANDBOX_S3_BUCKET: {{ .Values.sandbox.s3.bucket | quote }}
  SANDBOX_MAX_CONCURRENT_PER_ORG: {{ .Values.sandbox.maxConcurrentPerTenant | quote }}
  SANDBOX_IDLE_TIMEOUT_SECONDS: {{ .Values.sandbox.idleTimeoutSeconds | quote }}
  SANDBOX_SNAPSHOTS_ENABLED: {{ .Values.sandbox.snapshots.enabled | quote }}
  SANDBOX_SNAPSHOT_RETENTION_DAYS: {{ .Values.sandbox.snapshots.retentionDays | quote }}
{{- end }}
```

#### 4.8 API Deployment Updates

Add to `deployment/helm/charts/onyx/templates/api-deployment.yaml`:

```yaml
spec:
  template:
    spec:
      {{- if .Values.sandbox.enabled }}
      serviceAccountName: {{ include "onyx.fullname" . }}-sandbox-manager
      {{- end }}
      # ... rest of spec
```

### Phase 5: Database Schema Updates

#### 5.1 Migration

Create alembic migration to add Kubernetes-specific fields:

```python
def upgrade():
    # Add kubernetes-specific columns to sandbox table
    op.add_column('sandbox', sa.Column('pod_name', sa.String(), nullable=True))
    op.add_column('sandbox', sa.Column('service_name', sa.String(), nullable=True))
    op.add_column('sandbox', sa.Column('namespace', sa.String(), nullable=True))
    op.add_column('sandbox', sa.Column('pod_ip', sa.String(), nullable=True))

    # Add index for kubernetes lookups
    op.create_index('ix_sandbox_pod_name', 'sandbox', ['pod_name'])
    op.create_index('ix_sandbox_namespace', 'sandbox', ['namespace'])
```

### Phase 6: EKS Security Infrastructure (Terraform)

This phase covers the AWS infrastructure required to prevent sandboxes from accessing internal resources. The architecture uses defense-in-depth:

```
Sandbox Pods → Sandbox Node Subnet → AWS Network Firewall → NAT Gateway → Internet
```

#### 6.1 Dedicated Sandbox Node Group

Sandbox pods run on dedicated nodes with:
- Taints to prevent other workloads from scheduling
- Private subnets with firewall-routed egress
- IMDSv2 with hop limit = 1 to block container IMDS access

```hcl
# terraform/modules/sandbox-eks/node-group.tf

resource "aws_eks_node_group" "sandbox" {
  cluster_name    = var.eks_cluster_name
  node_group_name = "sandbox-workers"
  node_role_arn   = aws_iam_role.sandbox_node.arn
  subnet_ids      = aws_subnet.sandbox_private[*].id  # Dedicated private subnets

  scaling_config {
    desired_size = var.sandbox_node_desired
    max_size     = var.sandbox_node_max
    min_size     = 0
  }

  instance_types = var.sandbox_instance_types

  # Taint so only sandbox pods schedule here
  taint {
    key    = "workload"
    value  = "sandbox"
    effect = "NO_SCHEDULE"
  }

  labels = {
    "onyx.app/workload" = "sandbox"
  }

  launch_template {
    id      = aws_launch_template.sandbox_node.id
    version = aws_launch_template.sandbox_node.latest_version
  }

  tags = var.tags
}

resource "aws_launch_template" "sandbox_node" {
  name_prefix = "sandbox-node-"

  # CRITICAL: IMDSv2 required + hop limit = 1
  # This prevents containers from accessing the instance metadata service
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"  # IMDSv2 only (no IMDSv1)
    http_put_response_hop_limit = 1           # Blocks container access through network namespace
    instance_metadata_tags      = "disabled"
  }

  user_data = base64encode(templatefile("${path.module}/templates/sandbox-userdata.sh", {
    cluster_name     = var.eks_cluster_name
    cluster_endpoint = var.eks_cluster_endpoint
    cluster_ca       = var.eks_cluster_ca
  }))

  tag_specifications {
    resource_type = "instance"
    tags = merge(var.tags, {
      Name = "sandbox-worker"
    })
  }
}
```

#### 6.2 Minimal Node IAM Role

The sandbox node role has **minimum required permissions**. If a sandbox somehow steals node credentials (despite IMDS protections), the blast radius is limited.

```hcl
# terraform/modules/sandbox-eks/node-iam.tf

resource "aws_iam_role" "sandbox_node" {
  name = "${var.cluster_name}-sandbox-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })

  tags = var.tags
}

# Minimal policies - ONLY what EKS nodes need to function
resource "aws_iam_role_policy_attachment" "sandbox_node_cni" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.sandbox_node.name
}

resource "aws_iam_role_policy_attachment" "sandbox_node_worker" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.sandbox_node.name
}

# ECR read-only for pulling sandbox images from ECR pull-through cache
resource "aws_iam_role_policy_attachment" "sandbox_node_ecr" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.sandbox_node.name
}

# NOTE: NO additional policies!
# - NO S3 access
# - NO SecretsManager access
# - NO SSM access
# - NO IAM access
# - NO broad wildcards
```

#### 6.3 AWS Network Firewall

The Network Firewall sits between sandbox nodes and the NAT Gateway, blocking all traffic to internal/private IP ranges at the VPC edge. This is the **primary enforcement point** - NetworkPolicies are defense-in-depth.

```hcl
# terraform/modules/sandbox-eks/network-firewall.tf

resource "aws_networkfirewall_firewall" "sandbox_egress" {
  name                = "${var.cluster_name}-sandbox-egress"
  firewall_policy_arn = aws_networkfirewall_firewall_policy.sandbox.arn
  vpc_id              = var.vpc_id

  dynamic "subnet_mapping" {
    for_each = aws_subnet.firewall[*].id
    content {
      subnet_id = subnet_mapping.value
    }
  }

  tags = var.tags
}

resource "aws_networkfirewall_firewall_policy" "sandbox" {
  name = "${var.cluster_name}-sandbox-egress-policy"

  firewall_policy {
    stateless_default_actions          = ["aws:forward_to_sfe"]
    stateless_fragment_default_actions = ["aws:forward_to_sfe"]

    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.block_internal.arn
      priority     = 1
    }

    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.allow_external.arn
      priority     = 100
    }
  }

  tags = var.tags
}

# Rule group: Block all internal/private ranges
resource "aws_networkfirewall_rule_group" "block_internal" {
  name     = "${var.cluster_name}-block-internal"
  capacity = 100
  type     = "STATEFUL"

  rule_group {
    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }

    rules_source {
      # Block RFC1918 Class A (10.0.0.0/8)
      stateful_rule {
        action = "DROP"
        header {
          destination      = "10.0.0.0/8"
          destination_port = "ANY"
          direction        = "ANY"
          protocol         = "IP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["1"] }
      }

      # Block RFC1918 Class B (172.16.0.0/12)
      stateful_rule {
        action = "DROP"
        header {
          destination      = "172.16.0.0/12"
          destination_port = "ANY"
          direction        = "ANY"
          protocol         = "IP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["2"] }
      }

      # Block RFC1918 Class C (192.168.0.0/16)
      stateful_rule {
        action = "DROP"
        header {
          destination      = "192.168.0.0/16"
          destination_port = "ANY"
          direction        = "ANY"
          protocol         = "IP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["3"] }
      }

      # Block IMDS (169.254.169.254/32) - belt and suspenders with IMDSv2
      stateful_rule {
        action = "DROP"
        header {
          destination      = "169.254.169.254/32"
          destination_port = "ANY"
          direction        = "ANY"
          protocol         = "IP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["4"] }
      }

      # Block all link-local (169.254.0.0/16)
      stateful_rule {
        action = "DROP"
        header {
          destination      = "169.254.0.0/16"
          destination_port = "ANY"
          direction        = "ANY"
          protocol         = "IP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["5"] }
      }

      # Block CGNAT (100.64.0.0/10)
      stateful_rule {
        action = "DROP"
        header {
          destination      = "100.64.0.0/10"
          destination_port = "ANY"
          direction        = "ANY"
          protocol         = "IP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["6"] }
      }

      # Block loopback (127.0.0.0/8) - shouldn't route, but defense in depth
      stateful_rule {
        action = "DROP"
        header {
          destination      = "127.0.0.0/8"
          destination_port = "ANY"
          direction        = "ANY"
          protocol         = "IP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["7"] }
      }
    }
  }

  tags = var.tags
}

# Rule group: Allow external HTTPS and DNS
resource "aws_networkfirewall_rule_group" "allow_external" {
  name     = "${var.cluster_name}-allow-external"
  capacity = 50
  type     = "STATEFUL"

  rule_group {
    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }

    rules_source {
      # Allow HTTPS to anywhere (internal blocked by previous rule group)
      stateful_rule {
        action = "PASS"
        header {
          destination      = "ANY"
          destination_port = "443"
          direction        = "FORWARD"
          protocol         = "TCP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["100"] }
      }

      # Allow DNS to VPC resolver only
      stateful_rule {
        action = "PASS"
        header {
          destination      = "${cidrhost(var.vpc_cidr, 2)}/32"  # VPC DNS resolver (.2)
          destination_port = "53"
          direction        = "FORWARD"
          protocol         = "UDP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["101"] }
      }

      stateful_rule {
        action = "PASS"
        header {
          destination      = "${cidrhost(var.vpc_cidr, 2)}/32"
          destination_port = "53"
          direction        = "FORWARD"
          protocol         = "TCP"
          source           = "ANY"
          source_port      = "ANY"
        }
        rule_option { keyword = "sid"; settings = ["102"] }
      }
    }
  }

  tags = var.tags
}
```

#### 6.4 Route Tables for Firewall Path

Traffic from sandbox nodes routes through the Network Firewall before reaching the NAT Gateway.

```hcl
# terraform/modules/sandbox-eks/routes.tf

# Sandbox node subnets route to firewall
resource "aws_route_table" "sandbox_private" {
  vpc_id = var.vpc_id

  route {
    cidr_block      = "0.0.0.0/0"
    vpc_endpoint_id = tolist(aws_networkfirewall_firewall.sandbox_egress.firewall_status[0].sync_states)[0].attachment[0].endpoint_id
  }

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-sandbox-private-rt"
  })
}

resource "aws_route_table_association" "sandbox_private" {
  count          = length(aws_subnet.sandbox_private)
  subnet_id      = aws_subnet.sandbox_private[count.index].id
  route_table_id = aws_route_table.sandbox_private.id
}

# Firewall subnets route to NAT Gateway
resource "aws_route_table" "firewall" {
  vpc_id = var.vpc_id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = var.nat_gateway_id
  }

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-firewall-rt"
  })
}

resource "aws_route_table_association" "firewall" {
  count          = length(aws_subnet.firewall)
  subnet_id      = aws_subnet.firewall[count.index].id
  route_table_id = aws_route_table.firewall.id
}
```

#### 6.5 NACL as Backup

Network ACLs provide an additional layer of IMDS blocking that cannot be bypassed by pods.

```hcl
# terraform/modules/sandbox-eks/nacl.tf

resource "aws_network_acl" "sandbox" {
  vpc_id     = var.vpc_id
  subnet_ids = aws_subnet.sandbox_private[*].id

  # Explicitly block IMDS at NACL level (cannot be bypassed by pods)
  egress {
    protocol   = "-1"
    rule_no    = 10
    action     = "deny"
    cidr_block = "169.254.169.254/32"
    from_port  = 0
    to_port    = 0
  }

  # Allow all other egress (firewall handles filtering)
  egress {
    protocol   = "-1"
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }

  # Allow all ingress (return traffic, cluster communication)
  ingress {
    protocol   = "-1"
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-sandbox-nacl"
  })
}
```

#### 6.6 ECR Pull-Through Cache

Use ECR pull-through cache for sandbox images. This avoids Docker Hub rate limits and keeps image pulls internal (fast).

```hcl
# terraform/modules/sandbox-eks/ecr.tf

# Pull-through cache for Docker Hub
resource "aws_ecr_pull_through_cache_rule" "dockerhub" {
  ecr_repository_prefix = "dockerhub"
  upstream_registry_url = "registry-1.docker.io"
  credential_arn        = aws_secretsmanager_secret.dockerhub_creds.arn
}

# Secret for Docker Hub credentials (optional, for higher rate limits)
resource "aws_secretsmanager_secret" "dockerhub_creds" {
  name        = "${var.cluster_name}/dockerhub-credentials"
  description = "Docker Hub credentials for ECR pull-through cache"
  tags        = var.tags
}

# NOTE: Secret value must be set manually or via separate process:
# {
#   "username": "your-dockerhub-username",
#   "accessToken": "your-dockerhub-access-token"
# }
```

After setting up the pull-through cache, reference sandbox images as:
```
<account>.dkr.ecr.<region>.amazonaws.com/dockerhub/onyxdotapp/sandbox:latest
```

Update the Helm values to use this image path:
```yaml
sandbox:
  image:
    repository: <account>.dkr.ecr.<region>.amazonaws.com/dockerhub/onyxdotapp/sandbox
```

#### 6.7 S3 Bucket and IRSA Role for File Sync

The init container needs S3 access for syncing snapshots, knowledge files, and user uploads. This uses IRSA (IAM Roles for Service Accounts).

```hcl
# terraform/modules/sandbox-eks/s3.tf

# S3 bucket for sandbox files
resource "aws_s3_bucket" "sandbox_files" {
  bucket = "${var.cluster_name}-sandbox-files"
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "sandbox_files" {
  bucket = aws_s3_bucket.sandbox_files.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "sandbox_files" {
  bucket = aws_s3_bucket.sandbox_files.id

  # Expire old snapshots - uses tag-based filtering since snapshots are under
  # {tenant_id}/snapshots/ and S3 lifecycle rules don't support wildcards
  rule {
    id     = "expire-old-snapshots"
    status = "Enabled"

    filter {
      tag {
        key   = "Type"
        value = "snapshot"
      }
    }

    expiration {
      days = var.snapshot_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  # Clean up incomplete multipart uploads
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}  # Apply to all objects

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# NOTE: When creating snapshots, add the tag "Type=snapshot" to enable lifecycle expiration.
# Example in the snapshot upload command:
#   aws s3 cp - s3://{bucket}/{tenant}/snapshots/{session}/{id}.tar.gz --metadata Type=snapshot
# Or use: aws s3api put-object-tagging after upload

# Block public access
resource "aws_s3_bucket_public_access_block" "sandbox_files" {
  bucket = aws_s3_bucket.sandbox_files.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

```hcl
# terraform/modules/sandbox-eks/irsa.tf

# IRSA role for sandbox init container to access S3
resource "aws_iam_role" "sandbox_file_sync" {
  name = "${var.cluster_name}-sandbox-file-sync"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRoleWithWebIdentity"
      Effect = "Allow"
      Principal = {
        Federated = var.oidc_provider_arn
      }
      Condition = {
        StringEquals = {
          "${var.oidc_provider}:sub" = "system:serviceaccount:${var.sandbox_namespace}:sandbox-file-sync"
          "${var.oidc_provider}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "sandbox_file_sync_s3" {
  name = "s3-access"
  role = aws_iam_role.sandbox_file_sync.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.sandbox_files.arn,
          "${aws_s3_bucket.sandbox_files.arn}/*"
        ]
      }
    ]
  })
}

output "sandbox_file_sync_role_arn" {
  description = "ARN of the IRSA role for sandbox file sync"
  value       = aws_iam_role.sandbox_file_sync.arn
}

output "sandbox_s3_bucket" {
  description = "Name of the S3 bucket for sandbox files"
  value       = aws_s3_bucket.sandbox_files.id
}
```

#### 6.8 Subnet Layout

The sandbox infrastructure requires dedicated subnets:

```hcl
# terraform/modules/sandbox-eks/subnets.tf

# Sandbox node subnets (private, firewall-routed)
resource "aws_subnet" "sandbox_private" {
  count                   = length(var.availability_zones)
  vpc_id                  = var.vpc_id
  cidr_block              = cidrsubnet(var.sandbox_subnet_cidr, 2, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name                              = "${var.cluster_name}-sandbox-private-${var.availability_zones[count.index]}"
    "kubernetes.io/role/internal-elb" = "1"
  })
}

# Firewall subnets (between sandbox and NAT)
resource "aws_subnet" "firewall" {
  count                   = length(var.availability_zones)
  vpc_id                  = var.vpc_id
  cidr_block              = cidrsubnet(var.firewall_subnet_cidr, 2, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-firewall-${var.availability_zones[count.index]}"
  })
}
```

#### 6.9 Module Variables

```hcl
# terraform/modules/sandbox-eks/variables.tf

variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
}

variable "eks_cluster_name" {
  description = "EKS cluster name for node group"
  type        = string
}

variable "eks_cluster_endpoint" {
  description = "EKS cluster API endpoint"
  type        = string
}

variable "eks_cluster_ca" {
  description = "EKS cluster CA certificate"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
}

variable "nat_gateway_id" {
  description = "NAT Gateway ID for firewall egress"
  type        = string
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
}

variable "sandbox_subnet_cidr" {
  description = "CIDR block for sandbox subnets"
  type        = string
  default     = "10.0.64.0/18"
}

variable "firewall_subnet_cidr" {
  description = "CIDR block for firewall subnets"
  type        = string
  default     = "10.0.128.0/20"
}

variable "sandbox_node_desired" {
  description = "Desired number of sandbox nodes"
  type        = number
  default     = 2
}

variable "sandbox_node_max" {
  description = "Maximum number of sandbox nodes"
  type        = number
  default     = 10
}

variable "sandbox_instance_types" {
  description = "Instance types for sandbox nodes"
  type        = list(string)
  default     = ["m6i.large"]
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS OIDC provider for IRSA"
  type        = string
}

variable "oidc_provider" {
  description = "EKS OIDC provider URL (without https://)"
  type        = string
}

variable "sandbox_namespace" {
  description = "Kubernetes namespace for sandbox pods"
  type        = string
  default     = "onyx-sandboxes"
}

variable "snapshot_retention_days" {
  description = "Number of days to retain snapshots in S3"
  type        = number
  default     = 30
}
```

#### 6.10 DNS Isolation

Ensure internal Route53 private hosted zones are NOT associated with sandbox subnets. This prevents sandboxes from resolving internal DNS names.

If you have internal services accessible via Route53 private hosted zones:
1. Do NOT associate those zones with the sandbox VPC subnets
2. Or use a separate VPC for sandboxes entirely

For existing deployments, verify no private hosted zone associations exist:

```bash
# List private hosted zones and their VPC associations
aws route53 list-hosted-zones-by-vpc --vpc-id <sandbox-vpc-id> --vpc-region <region>
```

## File Summary

### New Files

#### Backend (Python)

| Path | Purpose |
|------|---------|
| `backend/onyx/server/features/build/sandbox/kubernetes_manager.py` | KubernetesSandboxManager implementation |
| `backend/onyx/server/features/build/sandbox/internal/acp_http_client.py` | HTTP-based ACP client |
| `backend/onyx/server/features/build/sandbox/docker/Dockerfile` | Sandbox container image |
| `backend/onyx/server/features/build/sandbox/docker/entrypoint.sh` | Container entrypoint script |

#### Helm Templates

| Path | Purpose |
|------|---------|
| `deployment/helm/charts/onyx/templates/sandbox-rbac.yaml` | RBAC for sandbox management |
| `deployment/helm/charts/onyx/templates/sandbox-namespace.yaml` | Sandbox namespace with Pod Security Standards |
| `deployment/helm/charts/onyx/templates/sandbox-limitrange.yaml` | Resource defaults |
| `deployment/helm/charts/onyx/templates/sandbox-resourcequota.yaml` | Total resource limits |
| `deployment/helm/charts/onyx/templates/sandbox-networkpolicy.yaml` | Network isolation (defense-in-depth) |

#### Terraform (EKS Security Infrastructure)

| Path | Purpose |
|------|---------|
| `terraform/modules/sandbox-eks/node-group.tf` | Dedicated sandbox node group with taints |
| `terraform/modules/sandbox-eks/node-iam.tf` | Minimal node IAM role |
| `terraform/modules/sandbox-eks/network-firewall.tf` | AWS Network Firewall rules |
| `terraform/modules/sandbox-eks/routes.tf` | Route tables for firewall path |
| `terraform/modules/sandbox-eks/nacl.tf` | NACL for IMDS blocking |
| `terraform/modules/sandbox-eks/ecr.tf` | ECR pull-through cache |
| `terraform/modules/sandbox-eks/s3.tf` | S3 bucket for sandbox files (snapshots, knowledge, uploads) |
| `terraform/modules/sandbox-eks/irsa.tf` | IRSA role for init container S3 access |
| `terraform/modules/sandbox-eks/subnets.tf` | Dedicated sandbox/firewall subnets |
| `terraform/modules/sandbox-eks/variables.tf` | Module variables |
| `terraform/modules/sandbox-eks/templates/sandbox-userdata.sh` | Node bootstrap script |

### Modified Files

| Path | Changes |
|------|---------|
| `backend/onyx/server/features/build/sandbox/manager.py` | Add factory function, update abstract interface |
| `backend/onyx/server/features/build/configs.py` | Add Kubernetes config variables (namespace, image, S3 bucket) |
| `backend/onyx/db/models.py` | Add Kubernetes-specific sandbox fields (pod_name, service_name, namespace, pod_ip) |
| `backend/requirements/default.txt` | Add `kubernetes` package |
| `deployment/helm/charts/onyx/values.yaml` | Add `sandbox` section with S3 config, node affinity, ephemeral storage limits |
| `deployment/helm/charts/onyx/templates/configmap.yaml` | Add sandbox env vars |
| `deployment/helm/charts/onyx/templates/api-deployment.yaml` | Add service account |
| `deployment/helm/charts/onyx/Chart.yaml` | Version bump |
