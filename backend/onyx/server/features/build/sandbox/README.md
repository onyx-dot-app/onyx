# Onyx Sandbox System

This directory contains the implementation of Onyx's sandbox system for running OpenCode agents in isolated environments.

## Local Development

Craft requires a local kind cluster — see [Local Kubernetes Development](/docs/craft/dev/local-kubernetes.md). One-shot setup: `make craft-up`.

## Overview

The sandbox system provides isolated execution environments where OpenCode agents can build web applications, run code, and interact with knowledge files. Each sandbox includes:

- **Next.js development environment** - Lightweight Next.js scaffold with shadcn/ui and Recharts for building UIs
- **Python virtual environment** - Pre-installed packages for data processing
- **OpenCode agent** - AI coding agent with access to tools and MCP servers
- **Knowledge files** - Access to indexed documents and user uploads

## Architecture

### Deployment Modes

1. **Kubernetes Mode** (`SANDBOX_BACKEND=kubernetes`) — default
   - Sandboxes run as Kubernetes pods, one per user
   - Each pod has one app container (`sandbox`) plus one native restartable init sidecar (`sidecar`) for push/snapshot control-plane work
   - api_server talks to the Kubernetes API for pod lifecycle and `kubectl exec`
   - Automatic snapshots stream through the in-pod sidecar to the api_server-owned `FileStore`
   - Auto-cleanup of idle sandboxes
   - Production-ready with resource isolation, security context, and NetworkPolicies
   - Requires Kubernetes `>= 1.33` for native restartable init sidecar containers
   - Used by Onyx's Helm chart / cloud deployment
   - For local-cluster development, see [docs/craft/dev/local-kubernetes.md](/docs/craft/dev/local-kubernetes.md).

2. **Docker Mode** (`SANDBOX_BACKEND=docker`)
   - Sandboxes run as Docker containers on the same host as the rest of the compose stack, one per user
   - api_server mounts `/var/run/docker.sock` and talks to the Docker Engine API for container lifecycle and `docker exec`
   - Snapshots tar-streamed through api_server-owned `FileStore` — agent containers never receive S3/MinIO credentials
   - Auto-cleanup of idle sandboxes (background worker uses the same Docker socket)
   - For self-hosted `docker compose` deployments enabled by `install.sh --include-craft`
   - Sandboxes join only the dedicated `onyx_craft_sandbox` bridge — `postgres` / `redis` / `minio` / model servers are not reachable by compose DNS

#### Kubernetes → Docker mapping

The Docker backend is intentionally the closest single-VM analogue of the Kubernetes backend:

| Kubernetes                            | Docker compose                                              |
| ------------------------------------- | ----------------------------------------------------------- |
| Sandbox pod (`sandbox-<id>`)          | Sandbox container (`sandbox-<id8>`)                         |
| Pod `emptyDir` workspace volume       | Named volume mounted at `/workspace/sessions`               |
| `kubectl exec` for setup + file ops   | `docker exec` over the Docker Engine API                    |
| Sidecar snapshot daemon, no storage credentials | api_server tar-streams via `docker exec` → `FileStore` |
| `Service` + DNS for Next.js preview   | Container IP on `onyx_craft_sandbox` bridge, proxied        |
| `NetworkPolicy` for egress isolation  | Dedicated bridge network + host `DOCKER-USER` iptables rule |
| Per-pod resource requests/limits      | `SANDBOX_DOCKER_CPU_LIMIT` / `SANDBOX_DOCKER_MEMORY_LIMIT`  |

#### Docker mode trust boundary

`api_server` and `background` mount the host Docker socket so they can drive sandbox containers. Anything that can talk to that socket is effectively root on the host — only enable Craft on hosts you fully control. Sandbox containers themselves run unprivileged: `--security-opt no-new-privileges`, `--cap-drop ALL`, `user=1000:1000`, no Docker socket, and a fixed env allowlist (`ONYX_PAT` + `ONYX_SERVER_URL`).

`SANDBOX_API_SERVER_URL` must be the **public** HTTPS URL that the agent reaches Onyx through (same way any onyx-cli client would). Compose hostnames like `http://api_server:8080` do not resolve from inside the sandbox bridge.

On EC2 the Docker bridge by default routes to `169.254.169.254` (IMDS), which can hand out IAM credentials. `install.sh --include-craft` installs a host-level `DOCKER-USER` iptables rule to drop sandbox→IMDS traffic when it has sudo/iptables access, and prints the manual command otherwise. There is no application-level fallback — fix this at the host firewall.

### Directory Structure

```
/workspace/                          # Sandbox root (in container)
├── managed/skills/                  # Skills pushed at session setup
├── outputs/                         # Working directory
│   ├── web/                        # Lightweight Next.js app (shadcn/ui, Recharts)
│   ├── slides/                     # Generated presentations
│   ├── markdown/                   # Generated documents
│   └── graphs/                     # Generated visualizations
├── .venv/                          # Python virtual environment
├── files/                          # Symlink to knowledge files
├── attachments/                    # User uploads
├── AGENTS.md                       # Agent instructions
└── .opencode/
    └── skills                      # Symlink → /workspace/managed/skills
```

## Setup

### Running via Docker/Kubernetes

Deploy the normal Onyx application images with Craft enabled. The sandbox image
is selected from the same application version by default, so app tag `vX.Y.Z`
uses `onyxdotapp/sandbox:vX.Y.Z`.

**How it works:**

- **Sandbox image**: Published under the same tag as the app image and bakes in the web template (`/workspace/templates/outputs`) plus a pre-built Python venv (`/workspace/.venv`) from `initial-requirements.txt`
- **Native init sidecar daemon** (Kubernetes only): Starts before the sandbox app container, stays running for the pod lifetime, and packages/restores session snapshots on the pod-local filesystem
- **Sandbox startup**: Runs `bun install --frozen-lockfile` (hardlinks from the image's pre-warmed Bun cache) + `bun run dev`

## OpenCode Configuration

Each sandbox includes an OpenCode agent configured with:

- **LLM Provider**: Anthropic, OpenAI, Google, Bedrock, or Azure
- **Extended thinking**: High reasoning effort / thinking budgets for complex tasks
- **Tool permissions**: File operations, bash commands, web access
- **Disabled tools**: Configurable via `OPENCODE_DISABLED_TOOLS` env var

Configuration is generated dynamically in `util/opencode_config.py`.

## Key Components

### Managers

- **`base.py`** - Abstract base class defining the sandbox interface
- **`kubernetes/kubernetes_sandbox_manager.py`** - Kubernetes-based sandbox manager for Helm/cloud
- **`docker/docker_sandbox_manager.py`** - Docker Engine-based sandbox manager for docker-compose

### Managers (Shared)

- **`manager/snapshot_manager.py`** - Handles snapshot creation and restoration

### Utilities

- **`util/opencode_config.py`** - Generates OpenCode configuration with MCP support
- **`util/agent_instructions.py`** - Generates agent instructions (AGENTS.md)

### Templates

- **`image/templates/outputs/web/`** - Lightweight Next.js scaffold (shadcn/ui, Recharts) versioned with the backend code

### Sandbox Image (shared by both backends)

- **`image/Dockerfile`** - Sandbox container image (runs Next.js + OpenCode)
- **`image/entrypoint.sh`** - Container startup script
- **`image/sandbox_daemon/`** - In-pod push/snapshot daemon
- Built-in skill sources live in `backend/onyx/skills/builtin/` (pushed at session setup, not baked in)

## Environment Variables

### Core Settings

```bash
# Sandbox backend mode
SANDBOX_BACKEND=kubernetes|docker          # Default: kubernetes

# OpenCode configuration
OPENCODE_DISABLED_TOOLS=question           # Comma-separated list, default: question
```

### Kubernetes Settings

Kubernetes Craft sandboxes require Kubernetes `>= 1.33` because sandbox pods
use native restartable init sidecar containers (`initContainers[*].restartPolicy:
Always`). Helm installs with `ENABLE_CRAFT=true` and `SANDBOX_BACKEND=kubernetes`
fail during render/install on older clusters.

```bash
# Kubernetes namespace
SANDBOX_NAMESPACE=onyx-sandboxes          # Default: onyx-sandboxes

# Helm defaults the sandbox image to onyxdotapp/sandbox:${global.version}.
# SANDBOX_CONTAINER_IMAGE is an internal override.

# Snapshots use the normal Onyx FileStore configuration
FILE_STORE_BACKEND=s3|gcs|postgres
S3_FILE_STORE_BUCKET_NAME=onyx-file-store # when FILE_STORE_BACKEND=s3

# Service account
SANDBOX_SERVICE_ACCOUNT_NAME=sandbox      # No storage credentials required
```

### Docker Settings

```bash

# Public URL the sandbox agent uses to reach Onyx (HTTPS, externally resolvable —
# compose hostnames like http://api_server:8080 will not resolve from inside the
# sandbox bridge).
SANDBOX_API_SERVER_URL=https://onyx.your-org.example

# Host path of the Docker socket mounted into api_server/background
SANDBOX_DOCKER_SOCKET=/var/run/docker.sock      # Default: /var/run/docker.sock

# Dedicated bridge network. Pre-created by install.sh --include-craft (or run
# `docker network create onyx_craft_sandbox` manually). Sandboxes join *only*
# this network — compose services are not reachable by DNS from inside.
SANDBOX_DOCKER_NETWORK=onyx_craft_sandbox       # Default: onyx_craft_sandbox

# Prefix for per-sandbox named volumes (mounted at /workspace/sessions).
SANDBOX_DOCKER_VOLUME_PREFIX=onyx-sandbox       # Default: onyx-sandbox

# Per-container resource limits. Defaults match K8s pod *requests* (1 CPU / 2Gi)
# rather than limits, since single-VM compose deployments rarely have headroom
# to over-commit every sandbox.
SANDBOX_DOCKER_MEMORY_LIMIT=2g                  # Default: 2g
SANDBOX_DOCKER_CPU_LIMIT=1.0                    # Default: 1.0
```

### Lifecycle Settings

```bash
# Idle timeout before cleanup (seconds)
SANDBOX_IDLE_TIMEOUT_SECONDS=900          # Default: 900 (15 minutes)

# Max concurrent sandboxes per organization
SANDBOX_MAX_CONCURRENT_PER_ORG=10         # Default: 10
```

## Testing

### Integration Tests

```bash
# Test Kubernetes sandbox provisioning (requires kind cluster — see make craft-up)
uv run pytest backend/tests/integration/tests/craft/k8s/test_kubernetes_sandbox.py
```

## Troubleshooting

### Sandbox Stuck in PROVISIONING (Docker)

**Symptoms**: Sandbox status never changes from `PROVISIONING` in `docker compose` deployments

**Solutions**:

- Confirm `api_server` actually has the Docker socket: `docker compose exec api_server ls -l /var/run/docker.sock`
- Confirm the dedicated bridge exists: `docker network inspect onyx_craft_sandbox` (created by `install.sh --include-craft`, or run `docker network create onyx_craft_sandbox` manually)
- Check sandbox logs: `docker logs sandbox-<id8>`
- Confirm `SANDBOX_API_SERVER_URL` is a publicly resolvable HTTPS URL (the agent cannot reach `http://api_server:8080` from inside the sandbox bridge)

### Sandbox Stuck in PROVISIONING (Kubernetes)

**Symptoms**: Sandbox status never changes from `PROVISIONING`

**Solutions**:

- Check pod logs: `kubectl logs -n onyx-sandboxes sandbox-{sandbox-id}`
- Check sidecar logs: `kubectl logs -n onyx-sandboxes sandbox-{sandbox-id} -c sidecar`
- Verify the sandbox proxy host/CA configuration and ServiceAccount exist in the sandbox namespace

### Next.js Server Won't Start

**Symptoms**: Sandbox provisioned but web preview doesn't load

**Solutions**:

- Check container logs: `kubectl logs -n onyx-sandboxes sandbox-{sandbox-id}`
- Verify `bun install` succeeded (check entrypoint.sh logs)
- Check that web template was copied: `kubectl exec -n onyx-sandboxes sandbox-{sandbox-id} -- ls /workspace/outputs/web`

## Security Considerations

### Sandbox Isolation

- **Kubernetes pods** run with restricted security context (non-root, no privilege escalation)
- **Sandbox app containers and sidecar init containers** do not receive FileStore, S3, or MinIO credentials
- **Network policies** can restrict sandbox egress traffic
- **Resource limits** prevent resource exhaustion
- **Docker containers** run with `--security-opt no-new-privileges`, `--cap-drop ALL`, `user=1000:1000`, no Docker socket, and a fixed env allowlist (`ONYX_PAT` + `ONYX_SERVER_URL`)
- **Docker network isolation** is enforced by joining only the dedicated `onyx_craft_sandbox` bridge — compose's default network (postgres/redis/minio/model servers) is unreachable by DNS from inside a sandbox
- **EC2 IMDS** must be blocked at the host firewall (`install.sh --include-craft` installs a `DOCKER-USER` iptables rule on EC2 when sudo is available) — there is no app-level fallback

### Credentials Management

- LLM API keys are passed as environment variables (not stored in sandbox)
- User file access is read-only via symlinks
- Snapshots are stored through the normal Onyx `FileStore` and isolated by tenant-scoped snapshot paths

## Development

### Adding New MCP Servers

1. Add MCP configuration to `util/opencode_config.py`:

   ```python
   config["mcp"] = {
       "my-mcp": {
           "type": "local",
           "command": ["npx", "@my/mcp@latest"],
           "enabled": True,
       }
   }
   ```

2. Install required npm packages in web template (if needed)

3. Rebuild Docker image and templates

### Modifying Agent Instructions

Edit `AGENTS.template.md` in the build directory. This is populated with dynamic content by `util/agent_instructions.py`.

### Adding New Tools/Permissions

Update `util/opencode_config.py` to add/remove tool permissions in the `permission` section.

## Template Details

### Web Template

The lightweight Next.js template (`backend/onyx/server/features/build/sandbox/image/templates/outputs/web/`) includes:

- **Framework**: Next.js 16.1.4 with React 19.2.3
- **UI Library**: shadcn/ui components with Radix UI primitives
- **Styling**: Tailwind CSS v4 with custom theming support
- **Charts**: Recharts for data visualization
- **Size**: ~2MB (excluding node_modules, which are installed fresh per sandbox)

This template provides a modern development environment without the complexity of the full Onyx application, allowing agents to build custom UIs quickly.

### Python Venv Template

The Python venv (built into the sandbox image at `/workspace/.venv`) includes packages from `image/initial-requirements.txt`:

- Data processing: pandas, numpy, matplotlib
- HTTP clients: requests, httpx
- Utilities: python-dotenv, pydantic

## References

- [OpenCode Documentation](https://docs.opencode.ai)
- [Next.js Documentation](https://nextjs.org/docs)
- [shadcn/ui Components](https://ui.shadcn.com)
