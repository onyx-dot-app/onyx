# Sandbox Container Image
#
# User-shared sandbox: one pod per user, sessions created via kubectl exec.
# See docs/craft/sandbox/image-and-spinup.md for image-layer rationale.

# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to
# the ECR pull-through cache
# (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker Hub
# rate limits.
ARG BASE_IMAGE_REGISTRY=docker.io

# bun binary source. Pinned via the registry prefix in its own stage because
# buildx rejects variable expansion directly in `COPY --from=` — the ARG is
# only expandable in a FROM.
FROM ${BASE_IMAGE_REGISTRY}/oven/bun:1.3.14@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS bun_source

# Node.js source. The final image is Python-based, but the sandbox still needs
# Node/npm/npx for MCP commands and skill-runtime packages.
FROM ${BASE_IMAGE_REGISTRY}/library/node:24-trixie-slim@sha256:45fbb3ca3b6c7e6646cd2889d0ac7bf314bb180036da792221fc2f48fe4d43fb AS node_source
ARG NPM_VERSION=11.17.0
RUN npm install -g "npm@${NPM_VERSION}" && \
    npm cache clean --force && \
    rm -rf /root/.npm

# GitHub CLI (gh): downloaded + checksum-verified in its own stage (arch-matched
# via buildx's TARGETARCH) so only the binary lands in the final image.
FROM node_source AS gh_source
ARG GH_CLI_VERSION=2.94.0
ARG TARGETARCH
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    tarball="gh_${GH_CLI_VERSION}_linux_${arch}.tar.gz"; \
    base="https://github.com/cli/cli/releases/download/v${GH_CLI_VERSION}"; \
    cd /tmp; \
    curl -fsSL -o "${tarball}" "${base}/${tarball}"; \
    curl -fsSL -o checksums.txt "${base}/gh_${GH_CLI_VERSION}_checksums.txt"; \
    grep " ${tarball}\$" checksums.txt | sha256sum -c -; \
    tar -xzf "${tarball}"; \
    install -m 0755 "gh_${GH_CLI_VERSION}_linux_${arch}/bin/gh" /usr/local/bin/gh

FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:f82c96458eedc847b233e582eb31336f4954b39cae020b6dcf5b3ed0e5cbcd74

# Set ENABLE_SKILLS=false in dev/CI to skip skill-runtime deps (LibreOffice,
# poppler, fonts, pptxgenjs) and shave ~700 MB. Skills themselves are pushed by
# the API server at session-setup, but their runtime tools must already be in
# the image.
ARG ENABLE_SKILLS=true
ARG ENABLE_BROWSER=true
ARG OPENCODE_VERSION=1.15.7
ARG AGENT_BROWSER_VERSION=0.31.1

# firewall-init.sh needs: iptables (egress lockdown), ca-certificates (trust
# store), gosu (legacy, not currently invoked). setpriv ships with util-linux in
# the python:3.13-slim base.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl \
    git \
    procps \
    unzip \
    iptables \
    gosu \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node_source /usr/local/bin/node /usr/local/bin/node
COPY --from=node_source /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    ln -sf ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack

RUN if [ "$ENABLE_SKILLS" = "true" ]; then \
    apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libreoffice-core \
    libreoffice-common \
    libreoffice-impress \
    libreoffice-draw \
    poppler-utils \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-noto-core \
    fonts-noto-color-emoji \
    fonts-inter \
    fonts-montserrat \
    fonts-lato \
    fonts-ebgaramond \
    fonts-firacode \
    && rm -rf /var/lib/apt/lists/*; \
    fi

# Chromium engine + certutil (libnss3-tools imports the egress-proxy CA into
# Chromium's NSS db). Its own layer: big and rarely-changing, so an
# AGENT_BROWSER_VERSION bump below re-pulls only the small CLI layer, not this.
RUN if [ "$ENABLE_BROWSER" = "true" ]; then \
    apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    chromium \
    libnss3-tools \
    && rm -rf /var/lib/apt/lists/*; \
    fi

# agent-browser CLI/daemon. Do NOT run `agent-browser install` — it fetches
# Chrome-for-Testing (no arm64 build); we use system chromium via
# AGENT_BROWSER_EXECUTABLE_PATH. --allow-scripts lets the npm postinstall run on
# npm 11+.
RUN if [ "$ENABLE_BROWSER" = "true" ]; then \
    npm install -g --allow-scripts=agent-browser "agent-browser@${AGENT_BROWSER_VERSION}" && \
    agent-browser --version && \
    npm cache clean --force && \
    rm -rf /root/.npm; \
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
COPY --exclude=.DS_Store templates/pptx /workspace/templates/pptx
RUN chown -R sandbox:sandbox /workspace/templates

COPY initial-requirements.txt /tmp/initial-requirements.txt
RUN python3 -m venv /workspace/.venv && \
    /workspace/.venv/bin/pip install --no-cache-dir --upgrade pip && \
    /workspace/.venv/bin/pip install --no-cache-dir --only-binary=:all: -r /tmp/initial-requirements.txt && \
    rm -rf /tmp/initial-requirements.txt /root/.cache/pip && \
    chown -R sandbox:sandbox /workspace/.venv

ENV PATH="/workspace/.venv/bin:${PATH}"
ENV PYTHONPATH="/workspace"

RUN if [ "$ENABLE_SKILLS" = "true" ]; then \
    npm install -g pptxgenjs && \
    npm cache clean --force && \
    rm -rf /root/.npm; \
    fi

# bun copied from the binary-source stage defined at the top of this file.
COPY --from=bun_source /usr/local/bin/bun /usr/local/bin/bun
COPY --from=gh_source /usr/local/bin/gh /usr/local/bin/gh

# Default gh config for the sandbox user: HTTPS git remotes (the proxy is
# HTTP/HTTPS only, so SSH is unreachable) and no interactive prompts.
RUN mkdir -p /home/sandbox/.config/gh \
    && printf 'git_protocol: https\nprompt: disabled\n' \
    > /home/sandbox/.config/gh/config.yml \
    && chown -R sandbox:sandbox /home/sandbox/.config

USER sandbox
RUN curl -fsSL -o /tmp/opencode-install.sh https://opencode.ai/install && \
    bash /tmp/opencode-install.sh --version "${OPENCODE_VERSION}" --no-modify-path && \
    rm /tmp/opencode-install.sh
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

COPY browser-cli.sh /usr/local/bin/browser
RUN chmod 0755 /usr/local/bin/browser

RUN chown -R sandbox:sandbox /workspace

USER sandbox
WORKDIR /workspace

# 3000: Next.js dev server, 4096: opencode serve, 8731: push daemon
EXPOSE 3000 4096 8731

ENTRYPOINT ["/workspace/entrypoint.sh"]
