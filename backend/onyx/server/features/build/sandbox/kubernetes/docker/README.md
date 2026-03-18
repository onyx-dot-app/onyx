# Sandbox Container Image

This directory contains the Dockerfile and resources for building the Onyx Craft sandbox container image.

## Directory Structure

```
docker/
â”œâ”€â”€ Dockerfile              # Main container image definition
â”œâ”€â”€ demo_data.zip           # Demo data (extracted to /workspace/demo_data)
â”œâ”€â”€ skills/                 # Agent skills (image-generation, pptx, etc.)
â”œâ”€â”€ templates/
â”‚   â””â”€â”€ outputs/            # Web app scaffold template (Next.js)
â”œâ”€â”€ initial-requirements.txt # Python packages pre-installed in sandbox
â”œâ”€â”€ generate_agents_md.py   # Script to generate AGENTS.md for sessions
â””â”€â”€ README.md               # This file
```

## Building the Image

The sandbox image must be built for **amd64** architecture since our Kubernetes cluster runs on x86_64 nodes.

### Build for amd64 only (fastest)

```bash
cd backend/onyx/server/features/build/sandbox/kubernetes/docker
docker build --platform linux/amd64 -t onyxdotapp/sandbox:v0.1.x .
docker push onyxdotapp/sandbox:v0.1.x
```

### Build multi-arch (recommended for flexibility)

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t onyxdotapp/sandbox:v0.1.x \
  --push .
```

### Update the `latest` tag

After pushing a versioned tag, update `latest`:

```bash
docker tag onyxdotapp/sandbox:v0.1.x onyxdotapp/sandbox:latest
docker push onyxdotapp/sandbox:latest
```

Or with buildx:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t onyxdotapp/sandbox:v0.1.x \
  -t onyxdotapp/sandbox:latest \
  --push .
```

## Deploying a New Version

1. **Build and push** the new image (see above)

2. **Update the ConfigMap** in `cloud-deployment-yamls/onyx/configmap/env-configmap.yaml`:
   ```yaml
   SANDBOX_CONTAINER_IMAGE: "onyxdotapp/sandbox:v0.1.x"
   ```

3. **Apply the ConfigMap**:
   ```bash
   kubectl apply -f configmap/env-configmap.yaml
   ```

4. **Restart the API server** to pick up the new config:
   ```bash
   kubectl rollout restart deployment/api-server -n onyx
   ```

5. **Delete existing sandbox pods** (they will be recreated with the new image):
   ```bash
   kubectl delete pods -n onyx-sandboxes -l app.kubernetes.io/component=sandbox
   ```

## What's Baked Into the Image

- **Base**: `node:20-slim` (Debian-based)
- **Demo data**: `/workspace/demo_data/` - sample files for demo sessions
- **Skills**: `/workspace/skills/` - agent skills (image-generation, pptx, etc.)
- **Templates**: `/workspace/templates/outputs/` - Next.js web app scaffold
- **Python venv**: `/workspace/.venv/` with packages from `initial-requirements.txt`
- **OpenCode CLI**: Installed in `/home/sandbox/.opencode/bin/`

## Runtime Directory Structure

When a session is created, the following structure is set up in the pod:

```
/workspace/
â”œâ”€â”€ demo_data/              # Baked into image
â”œâ”€â”€ files/                  # Mounted volume, synced from S3
â”œâ”€â”€ skills/                 # Baked into image (agent skills)
â”œâ”€â”€ templates/              # Baked into image
â””â”€â”€ sessions/
    â””â”€â”€ $session_id/
        â”œâ”€â”€ .opencode/
        â”‚   â””â”€â”€ skills/     # Symlink to /workspace/skills
        â”œâ”€â”€ files/          # Symlink to /workspace/demo_data or /workspace/files
        â”œâ”€â”€ outputs/        # Copied from templates, contains web app
        â”œâ”€â”€ attachments/    # User-uploaded files
        â”œâ”€â”€ org_info/       # Demo persona info (if demo mode)
        â”œâ”€â”€ AGENTS.md       # Instructions for the AI agent
        â””â”€â”€ opencode.json   # OpenCode configuration
```

## Troubleshooting

### Verify image exists on Docker Hub

```bash
curl -s "https://hub.docker.com/v2/repositories/onyxdotapp/sandbox/tags" | jq '.results[].name'
```

### Check what image a pod is using

```bash
kubectl get pod <pod-name> -n onyx-sandboxes -o jsonpath='{.spec.containers[?(@.name=="sandbox")].image}'
```
