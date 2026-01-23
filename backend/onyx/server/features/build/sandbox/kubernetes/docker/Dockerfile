# Sandbox Container Image
#
# This image runs a sandbox environment with:
# - Next.js dev server for preview
# - OpenCode ACP server for agent communication
#
# The image expects:
# - /workspace/outputs to contain the Next.js app (copied by init container from backend image)
# - /workspace/files to contain knowledge files (synced by init container from S3)
# - /workspace/user_uploaded_files to contain user uploads (mounted as emptyDir)
# - /workspace/AGENTS.md to contain agent instructions (written by init container)
# - OPENCODE_CONFIG env var with JSON config for opencode

FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    procps \
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
RUN mkdir -p /workspace/outputs /workspace/files /workspace/user_uploaded_files /workspace/instructions && \
    chown -R sandbox:sandbox /workspace

# Install opencode CLI as sandbox user so it goes to their home directory
USER sandbox
RUN curl -fsSL https://opencode.ai/install | bash
USER root

# Add opencode to PATH (installs to ~/.opencode/bin)
ENV PATH="/home/sandbox/.opencode/bin:${PATH}"

# Set ownership
RUN chown -R sandbox:sandbox /workspace

# Copy scripts
COPY entrypoint.sh /entrypoint.sh
COPY generate_agents_md.py /usr/local/bin/generate_agents_md.py
RUN chmod +x /entrypoint.sh /usr/local/bin/generate_agents_md.py

# Switch to non-root user
USER sandbox
WORKDIR /workspace

# Expose ports
# - 3000: Next.js dev server
# - 8081: OpenCode ACP HTTP server
EXPOSE 3000 8081

# Start both Next.js and OpenCode ACP server
ENTRYPOINT ["/entrypoint.sh"]
