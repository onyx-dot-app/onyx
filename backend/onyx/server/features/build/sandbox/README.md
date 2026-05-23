# Onyx Sandbox System

This directory contains the implementation of Onyx's sandbox system for running OpenCode agents in isolated environments.

## Local Development

Craft requires a local kind cluster — see [Local Kubernetes Development](/docs/dev/local-kubernetes.md). One-shot setup: `make craft-up`.

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
   - api_server talks to the Kubernetes API for pod lifecycle and `kubectl exec`
   - Automatic snapshots to S3 via a sidecar container with IRSA credentials
   - Auto-cleanup of idle sandboxes
   - Production-ready with resource isolation, security context, and NetworkPolicies
   - Used by Onyx's Helm chart / cloud deployment
   - For local-cluster development, see [docs/dev/local-kubernetes.md](/docs/dev/local-kubernetes.md).

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
| `kubectl exec` for setup/file ops/ACP | `docker exec` over the Docker Engine API                    |
| Sidecar container for snapshots/IRSA  | api_server tar-streams via `docker exec` → `FileStore`      |
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

### Running via Docker/Kubernetes (Zero Setup!) 🎉

**No setup required!** Just build and deploy:

```bash
# Build backend image (includes both templates)
cd backend
docker build -f Dockerfile.sandbox-templates -t onyxdotapp/backend:latest .

# Build sandbox container (lightweight runner)
cd onyx/server/features/build/sandbox/kubernetes/docker
docker build -t onyxdotapp/sandbox:latest .

# Deploy with docker-compose or kubectl - sandboxes work immediately!
```

**How it works:**

- **Backend image**: Contains both templates at build time:
  - Web template at `/templates/outputs/web` (lightweight Next.js scaffold, ~2MB)
  - Python venv template at `/templates/venv` (pre-installed packages, ~50MB)
- **Init container** (Kubernetes only): Syncs knowledge files from S3
- **Sandbox startup**: Runs `bun install --frozen-lockfile` (hardlinks from the image's pre-warmed Bun cache) + `bun run dev`

### Running Backend Directly (Without Docker)

**Only needed if you're running the Onyx backend outside of Docker.** Most developers use Docker and can skip this section.

If you're running the backend Python process directly on your machine, you need templates at `/templates/`:

#### Web Template

The web template is a lightweight Next.js app (Next.js 16, React 19, shadcn/ui, Recharts) checked into the codebase at `backend/onyx/server/features/build/templates/outputs/web/`.

For local development, create a symlink to this template:

```bash
sudo mkdir -p /templates/outputs
sudo ln -s $(pwd)/backend/onyx/server/features/build/templates/outputs/web /templates/outputs/web
```

#### Python Venv Template

If you don't have a venv template, create it:

```bash
# Use the utility script
cd backend
python -m onyx.server.features.build.sandbox.util.build_venv_template

# Or manually
python3 -m venv /templates/venv
/templates/venv/bin/pip install -r backend/onyx/server/features/build/sandbox/kubernetes/docker/initial-requirements.txt
```

#### System Dependencies (for PPTX skill)

The PPTX skill requires LibreOffice and Poppler for PDF conversion and thumbnail generation:

**macOS:**

```bash
brew install poppler
brew install --cask libreoffice
```

Ensure `soffice` is on your PATH:

```bash
export PATH="/Applications/LibreOffice.app/Contents/MacOS:$PATH"
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt-get install libreoffice-impress poppler-utils
```

**That's it!** When sandboxes are created:

1. Web template is copied from `/templates/outputs/web`
2. Python venv is copied from `/templates/venv`
3. `bun install --frozen-lockfile` runs automatically, hardlinking from the image's pre-warmed Bun tarball cache

## OpenCode Configuration

Each sandbox includes an OpenCode agent configured with:

- **LLM Provider**: Anthropic, OpenAI, Google, Bedrock, or Azure
- **Extended thinking**: High reasoning effort / thinking budgets for complex tasks
- **Tool permissions**: File operations, bash commands, web access
- **Disabled tools**: Configurable via `OPENCODE_DISABLED_TOOLS` env var

Configuration is generated dynamically in `templates/opencode_config.py`.

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

- **`../templates/outputs/web/`** - Lightweight Next.js scaffold (shadcn/ui, Recharts) versioned with the backend code

### Kubernetes Specific

- **`kubernetes/docker/Dockerfile`** - Sandbox container image (runs Next.js + OpenCode)
- **`kubernetes/docker/entrypoint.sh`** - Container startup script

## Environment Variables

### Core Settings

```bash
# Sandbox backend mode
SANDBOX_BACKEND=kubernetes|docker          # Default: kubernetes

# OpenCode configuration
OPENCODE_DISABLED_TOOLS=question           # Comma-separated list, default: question
```

### Kubernetes Settings

```bash
# Kubernetes namespace
SANDBOX_NAMESPACE=onyx-sandboxes          # Default: onyx-sandboxes

# Container image
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:latest

# S3 bucket for snapshots and files
SANDBOX_S3_BUCKET=onyx-sandbox-files      # Default: onyx-sandbox-files

# Service account
SANDBOX_SERVICE_ACCOUNT_NAME=sandbox-file-sync  # Has S3 access via IRSA for snapshots
```

### Docker Settings

```bash
# Container image (defaults to a pinned tag in docker-compose.yml)
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:v0.1.44

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
uv run pytest backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox.py
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
- Verify init container completed: `kubectl describe pod -n onyx-sandboxes sandbox-{sandbox-id}`
- Check S3 bucket access: Ensure init container service account has IRSA configured

### Next.js Server Won't Start

**Symptoms**: Sandbox provisioned but web preview doesn't load

**Solutions**:

- Check container logs: `kubectl logs -n onyx-sandboxes sandbox-{sandbox-id}`
- Verify `bun install` succeeded (check entrypoint.sh logs)
- Check that web template was copied: `kubectl exec -n onyx-sandboxes sandbox-{sandbox-id} -- ls /workspace/outputs/web`

## Security Considerations

### Sandbox Isolation

- **Kubernetes pods** run with restricted security context (non-root, no privilege escalation)
- **Init containers** have S3 access for file sync, but main sandbox container does NOT
- **Network policies** can restrict sandbox egress traffic
- **Resource limits** prevent resource exhaustion
- **Docker containers** run with `--security-opt no-new-privileges`, `--cap-drop ALL`, `user=1000:1000`, no Docker socket, and a fixed env allowlist (`ONYX_PAT` + `ONYX_SERVER_URL`)
- **Docker network isolation** is enforced by joining only the dedicated `onyx_craft_sandbox` bridge — compose's default network (postgres/redis/minio/model servers) is unreachable by DNS from inside a sandbox
- **EC2 IMDS** must be blocked at the host firewall (`install.sh --include-craft` installs a `DOCKER-USER` iptables rule on EC2 when sudo is available) — there is no app-level fallback

### Credentials Management

- LLM API keys are passed as environment variables (not stored in sandbox)
- User file access is read-only via symlinks
- Snapshots are isolated per tenant in S3

## Development

### Adding New MCP Servers

1. Add MCP configuration to `templates/opencode_config.py`:

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

Edit `AGENTS.template.md` in the build directory. This is populated with dynamic content by `templates/agent_instructions.py`.

### Adding New Tools/Permissions

Update `templates/opencode_config.py` to add/remove tool permissions in the `permission` section.

## Template Details

### Web Template

The lightweight Next.js template (`backend/onyx/server/features/build/templates/outputs/web/`) includes:

- **Framework**: Next.js 16.1.4 with React 19.2.3
- **UI Library**: shadcn/ui components with Radix UI primitives
- **Styling**: Tailwind CSS v4 with custom theming support
- **Charts**: Recharts for data visualization
- **Size**: ~2MB (excluding node_modules, which are installed fresh per sandbox)

This template provides a modern development environment without the complexity of the full Onyx application, allowing agents to build custom UIs quickly.

### Python Venv Template

The Python venv (`/templates/venv/`) includes packages from `initial-requirements.txt`:

- Data processing: pandas, numpy, polars
- HTTP clients: requests, httpx
- Utilities: python-dotenv, pydantic

## References

- [OpenCode Documentation](https://docs.opencode.ai)
- [Next.js Documentation](https://nextjs.org/docs)
- [shadcn/ui Components](https://ui.shadcn.com)
