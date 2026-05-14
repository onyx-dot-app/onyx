# Sandbox Container Image

This directory contains the Dockerfile and resources for building the Onyx Craft sandbox container image.

## Directory Structure

```
docker/
├── Dockerfile              # Main container image definition
├── skills/                 # Agent skills (company-search, image-generation, pptx, etc.)
├── templates/
│   └── outputs/            # Web app scaffold template (Next.js)
├── initial-requirements.txt # Python packages pre-installed in sandbox
└── README.md               # This file
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

2. **Update the ConfigMap** in in the internal repo
   ```yaml
   SANDBOX_CONTAINER_IMAGE: "onyxdotapp/sandbox:v0.1.x"
   ```

3. **Apply the ConfigMap**:
   ```bash
   kubectl apply -f configmap/env-configmap.yaml
   ```

4. **Restart the API server** to pick up the new config:
   ```bash
   kubectl rollout restart deployment/api-server -n danswer
   ```

5. **Delete existing sandbox pods** (they will be recreated with the new image):
   ```bash
   kubectl delete pods -n onyx-sandboxes -l app.kubernetes.io/component=sandbox
   ```

## What's Baked Into the Image

- **Base**: `node:20-slim` (Debian-based)
- **Skills**: `/workspace/skills/` — agent skills (company-search, image-generation, pptx)
- **Templates**: `/workspace/templates/outputs/` — Next.js web app scaffold
- **Python venv**: `/workspace/.venv/` with packages from `initial-requirements.txt`
- **OpenCode CLI**: Installed in `/home/sandbox/.opencode/bin/`
- **onyx-cli**: `/usr/local/bin/onyx-cli` — Onyx CLI for search
- **AWS CLI**: For S3 snapshot operations

## Runtime Directory Structure

When a session is created, the following structure is set up in the pod:

```
/workspace/
├── skills/                 # Baked into image (agent skills)
├── templates/              # Baked into image
└── sessions/
    └── $session_id/
        ├── .opencode/
        │   └── skills/     # Symlink to /workspace/skills
        ├── outputs/        # Copied from templates, contains web app
        ├── attachments/    # User-uploaded files
        ├── org_info/       # Demo persona info (if demo mode)
        ├── AGENTS.md       # Instructions for the AI agent
        └── opencode.json   # OpenCode configuration
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
