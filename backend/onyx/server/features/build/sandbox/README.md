# Onyx Sandbox System

This directory contains the implementation of Onyx's sandbox system for running OpenCode agents in isolated environments.

## Overview

The sandbox system provides isolated execution environments where OpenCode agents can build web applications, run code, and interact with knowledge files. Each sandbox includes:

- **Next.js development environment** - Lightweight Next.js scaffold with shadcn/ui and Recharts for building UIs
- **Python virtual environment** - Pre-installed packages for data processing
- **OpenCode agent** - AI coding agent with access to tools and MCP servers
- **Knowledge files** - Access to indexed documents and user uploads

## Architecture

### Deployment Modes

1. **Local Mode** (`SANDBOX_BACKEND=local`)
   - Sandboxes run as directories on the local filesystem
   - No automatic cleanup or snapshots
   - Suitable for development and testing

2. **Kubernetes Mode** (`SANDBOX_BACKEND=kubernetes`)
   - Sandboxes run as Kubernetes pods
   - Automatic snapshots to S3
   - Auto-cleanup of idle sandboxes
   - Production-ready with resource isolation

### Directory Structure

```
/workspace/                          # Sandbox root (in container)
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
    └── skills/                     # Agent skills
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
- **Sandbox startup**: Runs `npm install` (for fresh dependency locks) + `next dev`

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
3. `npm install` runs automatically to install fresh Next.js dependencies

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
- **`local/manager.py`** - Filesystem-based sandbox manager for local development
- **`kubernetes/manager.py`** - Kubernetes-based sandbox manager for production

### Managers (Shared)

- **`manager/directory_manager.py`** - Creates sandbox directory structure and copies templates
- **`manager/snapshot_manager.py`** - Handles snapshot creation and restoration

### Utilities

- **`util/opencode_config.py`** - Generates OpenCode configuration with MCP support
- **`util/agent_instructions.py`** - Generates agent instructions (AGENTS.md)
- **`util/build_venv_template.py`** - Utility to build Python venv template for local development

### Templates

- **`../templates/outputs/web/`** - Lightweight Next.js scaffold (shadcn/ui, Recharts) versioned with the backend code

### Kubernetes Specific

- **`kubernetes/docker/Dockerfile`** - Sandbox container image (runs Next.js + OpenCode)
- **`kubernetes/docker/entrypoint.sh`** - Container startup script

## Environment Variables

### Core Settings

```bash
# Sandbox backend mode
SANDBOX_BACKEND=local|kubernetes           # Default: local

# Template paths (local mode)
OUTPUTS_TEMPLATE_PATH=/templates/outputs   # Default: /templates/outputs
VENV_TEMPLATE_PATH=/templates/venv        # Default: /templates/venv

# Sandbox base path (local mode)
SANDBOX_BASE_PATH=/tmp/onyx-sandboxes     # Default: /tmp/onyx-sandboxes

# OpenCode configuration
OPENCODE_DISABLED_TOOLS=question          # Comma-separated list, default: question
```

### Kubernetes Settings

```bash
# Kubernetes namespace
SANDBOX_NAMESPACE=onyx-sandboxes          # Default: onyx-sandboxes

# Container image
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:latest

# S3 bucket for snapshots and files
SANDBOX_S3_BUCKET=onyx-sandbox-files      # Default: onyx-sandbox-files

# Service accounts
SANDBOX_SERVICE_ACCOUNT_NAME=sandbox-runner          # No AWS access
SANDBOX_FILE_SYNC_SERVICE_ACCOUNT=sandbox-file-sync  # Has S3 access via IRSA
```

### Lifecycle Settings

```bash
# Idle timeout before cleanup (seconds)
SANDBOX_IDLE_TIMEOUT_SECONDS=900          # Default: 900 (15 minutes)

# Max concurrent sandboxes per organization
SANDBOX_MAX_CONCURRENT_PER_ORG=10         # Default: 10

# Next.js port range (local mode)
SANDBOX_NEXTJS_PORT_START=3010            # Default: 3010
SANDBOX_NEXTJS_PORT_END=3100              # Default: 3100
```

## Testing

### Integration Tests

```bash
# Test local sandbox provisioning
uv run pytest backend/tests/integration/sandbox/test_local_sandbox.py

# Test Kubernetes sandbox provisioning (requires k8s cluster)
uv run pytest backend/tests/integration/sandbox/test_kubernetes_sandbox.py
```

### Manual Testing

```bash
# Start a local sandbox session
curl -X POST http://localhost:3000/api/build/session \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "file_system_path": "/path/to/files"
  }'

# Send a message to the agent
curl -X POST http://localhost:3000/api/build/session/{session_id}/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Create a simple web page"
  }'
```

## Troubleshooting

### Sandbox Stuck in PROVISIONING (Kubernetes)

**Symptoms**: Sandbox status never changes from `PROVISIONING`

**Solutions**:

- Check pod logs: `kubectl logs -n onyx-sandboxes sandbox-{sandbox-id}`
- Check init container: `kubectl logs -n onyx-sandboxes sandbox-{sandbox-id} -c file-sync`
- Verify init container completed: `kubectl describe pod -n onyx-sandboxes sandbox-{sandbox-id}`
- Check S3 bucket access: Ensure init container service account has IRSA configured

### Next.js Server Won't Start

**Symptoms**: Sandbox provisioned but web preview doesn't load

**Solutions**:

- **Local mode**: Check if port is already in use
- **Docker/K8s**: Check container logs: `kubectl logs -n onyx-sandboxes sandbox-{sandbox-id}`
- Verify npm install succeeded (check entrypoint.sh logs)
- Check that web template was copied: `kubectl exec -n onyx-sandboxes sandbox-{sandbox-id} -- ls /workspace/outputs/web`

### Templates Not Found (Local Mode)

**Symptoms**: `RuntimeError: Sandbox templates are missing`

**Solution**: Set up templates as described in the "Local Development" section above:

```bash
# Symlink web template
sudo ln -s $(pwd)/backend/onyx/server/features/build/templates/outputs/web /templates/outputs/web

# Create Python venv
python3 -m venv /templates/venv
/templates/venv/bin/pip install -r backend/onyx/server/features/build/sandbox/kubernetes/docker/initial-requirements.txt
```

### Permission Denied

**Symptoms**: `Permission denied` error accessing `/templates/`

**Solution**: Either use sudo when creating symlinks, or use custom paths:

```bash
export OUTPUTS_TEMPLATE_PATH=$HOME/.onyx/templates/outputs
export VENV_TEMPLATE_PATH=$HOME/.onyx/templates/venv

# Then symlink to your home directory
mkdir -p $HOME/.onyx/templates/outputs
ln -s $(pwd)/backend/onyx/server/features/build/templates/outputs/web $HOME/.onyx/templates/outputs/web
```

## Security Considerations

### Sandbox Isolation

- **Kubernetes pods** run with restricted security context (non-root, no privilege escalation)
- **Init containers** have S3 access for file sync, but main sandbox container does NOT
- **Network policies** can restrict sandbox egress traffic
- **Resource limits** prevent resource exhaustion

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
