# Sandbox Container Image
#
# User-shared sandbox: one pod per user, sessions created via kubectl exec.
# See docs/craft/sandbox/image-and-spinup.md for image-layer rationale.

# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to
# the ECR pull-through cache
# (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker Hub
# rate limits.
ARG BASE_IMAGE_REGISTRY=docker.io

# bun + s5cmd binary sources. Pinned via the registry prefix in their own stages
# because buildx rejects variable expansion directly in `COPY --from=` -- the
# ARG is only expandable in a FROM.
FROM ${BASE_IMAGE_REGISTRY}/oven/bun:1.3.14@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS bun_source
FROM ${BASE_IMAGE_REGISTRY}/peakcom/s5cmd:v2.3.0@sha256:2ff939e2ee3c76adcadd78dbfc3e2569b18a3743ed9dcfccb1ec589af7fb9903 AS s5cmd_source

FROM ${BASE_IMAGE_REGISTRY}/library/node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

# Set ENABLE_SKILLS=false in dev/CI to skip skill-runtime deps (LibreOffice,
# poppler, fonts, pptxgenjs) and shave ~700 MB. Skills themselves are pushed by
# the API server at session-setup, but their runtime tools must already be in
# the image.
ARG ENABLE_SKILLS=true
ARG OPENCODE_VERSION=1.15.7

# Install system dependencies.
# firewall-init.sh needs: iptables (egress lockdown), libcap2-bin (capsh to drop
# CAP_NET_ADMIN/SETPCAP from the bounding set in compose entrypoint mode), gosu
# (kept for compatibility / future drops), ca-certificates (CA trust-store
# population).
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    procps \
    unzip \
    gcc \
    libc6-dev \
    iptables \
    libcap2-bin \
    gosu \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN if [ "$ENABLE_SKILLS" = "true" ]; then \
    apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core \
    libreoffice-common \
    libreoffice-impress \
    libreoffice-draw \
    poppler-utils \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*; \
    fi

# Reconcile UID/GID 1000 with whatever the base image already ships with.
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

RUN mkdir -p /workspace/sessions /workspace/templates /workspace/managed && \
    chown -R sandbox:sandbox /workspace

COPY --exclude=.next --exclude=node_modules templates/outputs /workspace/templates/outputs
RUN chown -R sandbox:sandbox /workspace/templates

COPY initial-requirements.txt /tmp/initial-requirements.txt
RUN python3 -m venv /workspace/.venv && \
    /workspace/.venv/bin/pip install --no-cache-dir --upgrade pip && \
    /workspace/.venv/bin/pip install --no-cache-dir -r /tmp/initial-requirements.txt && \
    rm -rf /tmp/initial-requirements.txt /root/.cache/pip && \
    chown -R sandbox:sandbox /workspace/.venv

ENV PATH="/workspace/.venv/bin:${PATH}"
ENV PYTHONPATH="/workspace:${PYTHONPATH}"

RUN if [ "$ENABLE_SKILLS" = "true" ]; then \
    npm install -g pptxgenjs && \
    npm cache clean --force && \
    rm -rf /root/.npm; \
    fi

# bun + s5cmd copied from the binary-source stages defined at the top of this file.
COPY --from=bun_source /usr/local/bin/bun /usr/local/bin/bun
COPY --from=s5cmd_source /s5cmd /usr/local/bin/s5cmd

USER sandbox
RUN curl -fsSL https://opencode.ai/install \
    | bash -s -- --version "${OPENCODE_VERSION}" --no-modify-path
# Pre-warm Bun's tarball cache so per-session installs hit a local store.
RUN cd /workspace/templates/outputs/web && \
    bun install --frozen-lockfile && \
    rm -rf node_modules
USER root

ENV PATH="/home/sandbox/.opencode/bin:${PATH}"

COPY --exclude=__pycache__ sandbox_daemon/ /workspace/sandbox_daemon/
COPY entrypoint.sh /workspace/entrypoint.sh
COPY sidecar-entrypoint.sh /workspace/sidecar-entrypoint.sh

# Egress proxy bootstrap, run as the initContainer command / compose entrypoint.
COPY firewall-init.sh /workspace/firewall-init.sh
RUN chmod +x /workspace/firewall-init.sh

# Per-session egress tagging plugin. Path must match
# kubernetes_sandbox_manager._OPENCODE_SESSION_TAG_PLUGIN_PATH.
COPY opencode-plugins/ /workspace/opencode-plugins/

RUN chown -R sandbox:sandbox /workspace

USER sandbox
WORKDIR /workspace

# 3000: Next.js dev server, 4096: opencode serve, 8731: push daemon
EXPOSE 3000 4096 8731

ENTRYPOINT ["/workspace/entrypoint.sh"]
