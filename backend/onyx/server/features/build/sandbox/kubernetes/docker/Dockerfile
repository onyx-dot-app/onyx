# Sandbox Container Image
#
# This image runs a sandbox environment with:
# - Next.js dev server for preview
# - OpenCode ACP server for agent communication
#
# The image expects:
# - /workspace/outputs to contain the Next.js app (mounted as emptyDir, populated by init container)
# - /workspace/files to contain knowledge files (mounted as emptyDir, populated by init container)
# - /workspace/user_uploaded_files to contain user uploads (mounted as emptyDir, populated by init container)
# - /workspace/instructions to contain AGENTS.md (mounted from ConfigMap)
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
RUN groupadd -g 1000 sandbox && \
    useradd -u 1000 -g sandbox -m -s /bin/bash sandbox

# Create workspace directories
RUN mkdir -p /workspace/outputs /workspace/files /workspace/user_uploaded_files /workspace/instructions && \
    chown -R sandbox:sandbox /workspace

# Install opencode CLI
# Note: Update this URL to the actual opencode installation script
RUN curl -fsSL https://opencode.ai/install.sh | bash || \
    echo "OpenCode installation script not available, will need to be installed separately"

# Copy the pre-built Next.js template
# This will be overwritten by init container if restoring from snapshot
COPY outputs-template /workspace/outputs-template

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set ownership
RUN chown -R sandbox:sandbox /workspace

# Switch to non-root user
USER sandbox
WORKDIR /workspace

# Expose ports
# - 3000: Next.js dev server
# - 8081: OpenCode ACP HTTP server
EXPOSE 3000 8081

# Health check for the agent server
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8081/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
