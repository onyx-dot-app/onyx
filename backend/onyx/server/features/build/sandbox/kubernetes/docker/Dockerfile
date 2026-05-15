# Sandbox Container Image
#
# User-shared sandbox model:
# - One pod per user, shared across all user's sessions
# - Session workspaces created via kubectl exec (setup_session_workspace)
# - OpenCode agent runs via kubectl exec when needed
#
# Directory structure (created by init container + session setup):
#   /workspace/
#   ├── managed/skills/  # Pushed at session-setup time by the API server
#   ├── templates/       # Output templates (baked into image)
#   └── sessions/        # Per-session workspaces (created via exec)
#       └── $session_id/
#           ├── files/   # User's knowledge files (synced from S3)
#           ├── outputs/
#           ├── AGENTS.md
#           └── opencode.json

FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    procps \
    unzip \
    \
    libreoffice-core \
    libreoffice-common \
    libreoffice-impress \
    libreoffice-draw \
    poppler-utils \
    gcc \
    libc6-dev \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (matches pod securityContext)
# Handle existing user/group with UID/GID 1000 in base image
RUN EXISTING_USER=$(id -nu 1000 2>/dev/null || echo ""); \
    EXISTING_GROUP=$(getent group 1000 | cut -d: -f1 2>/dev/null || echo ""); \
    if [ -n "$EXISTING_GROUP" ] && [ "$EXISTING_GROUP" != "sandbox" ]; then \
    groupmod -n sandbox $EXISTING_GROUP; \
    elif [ -z "$EXISTING_GROUP" ]; then \
    groupadd -g 1000 sandbox; \
    fi; \
    if [ -n "$EXISTING_USER" ] && [ "$EXISTING_USER" != "sandbox" ]; then \
    usermod -l sandbox -g sandbox $EXISTING_USER; \
    usermod -d /home/sandbox -m sandbox; \
    usermod -s /bin/bash sandbox; \
    elif [ -z "$EXISTING_USER" ]; then \
    useradd -u 1000 -g sandbox -m -s /bin/bash sandbox; \
    fi

# Create workspace directories
RUN mkdir -p /workspace/sessions /workspace/templates /workspace/managed && \
    chown -R sandbox:sandbox /workspace

# Copy outputs template (web app scaffold, without node_modules)
COPY --exclude=.next --exclude=node_modules templates/outputs /workspace/templates/outputs
RUN chown -R sandbox:sandbox /workspace/templates

# Copy and install Python requirements into a venv
COPY initial-requirements.txt /tmp/initial-requirements.txt
RUN python3 -m venv /workspace/.venv && \
    /workspace/.venv/bin/pip install --no-cache-dir --upgrade pip && \
    /workspace/.venv/bin/pip install --no-cache-dir -r /tmp/initial-requirements.txt && \
    rm -rf /tmp/initial-requirements.txt /root/.cache/pip && \
    chown -R sandbox:sandbox /workspace/.venv

# Add venv to PATH so python/pip use it by default
ENV PATH="/workspace/.venv/bin:${PATH}"
ENV PYTHONPATH="/workspace:${PYTHONPATH}"

# Install pptxgenjs globally for creating presentations from scratch
RUN npm install -g pptxgenjs && \
    npm cache clean --force && \
    rm -rf /root/.npm

# Install opencode CLI as sandbox user so it goes to their home directory
USER sandbox
RUN curl -fsSL https://opencode.ai/install | bash
USER root

# Add opencode to PATH (installs to ~/.opencode/bin)
ENV PATH="/home/sandbox/.opencode/bin:${PATH}"

COPY --exclude=__pycache__ daemon/ /workspace/push_daemon/
COPY entrypoint.sh /workspace/entrypoint.sh

# Set ownership
RUN chown -R sandbox:sandbox /workspace

# Install AWS CLI (needed for snapshot operations)
COPY --from=amazon/aws-cli:latest /usr/local/aws-cli /usr/local/aws-cli
RUN ln -s /usr/local/aws-cli/v2/current/bin/aws /usr/local/bin/aws

# Switch to non-root user
USER sandbox
WORKDIR /workspace

# Expose ports
# - 3000: Next.js dev server (started per-session if needed)
# - 8081: OpenCode ACP HTTP server (started via exec)
# - 8731: Push daemon (receives tar.gz files from sandbox manager)
EXPOSE 3000 8081 8731

# Entrypoint runs push daemon + keeps container alive
ENTRYPOINT ["/workspace/entrypoint.sh"]
