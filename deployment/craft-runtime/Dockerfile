# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom
# Base images and tool versions are supplied by docker-bake.hcl.
ARG NODE_IMAGE
ARG PYTHON_IMAGE
ARG UV_IMAGE
FROM ${NODE_IMAGE} AS node_source
ARG NPM_VERSION
RUN --mount=type=secret,id=build_ca_bundle,mode=0444 \
    if [ -f /run/secrets/build_ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca_bundle; fi && \
    npm install -g "npm@${NPM_VERSION}" && \
    npm cache clean --force && rm -rf /root/.npm

FROM node_source AS javascript
ARG AGENT_BROWSER_VERSION
ARG PPTXGENJS_VERSION
ARG SHARP_VERSION
ARG LUCIDE_VERSION
ARG TABLER_VERSION
RUN --mount=type=secret,id=build_ca_bundle,mode=0444 \
    if [ -f /run/secrets/build_ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca_bundle; fi && \
    npm install -g --allow-scripts=agent-browser \
        "agent-browser@${AGENT_BROWSER_VERSION}" \
        "pptxgenjs@${PPTXGENJS_VERSION}" "sharp@${SHARP_VERSION}" && \
    npm uninstall -g --ignore-scripts corepack && \
    npm install --prefix /tmp/icons --ignore-scripts \
        "lucide-static@${LUCIDE_VERSION}" "@tabler/icons@${TABLER_VERSION}" && \
    mkdir -p /opt/onyx/assets/icons/lucide /opt/onyx/assets/icons/tabler && \
    cp -a /tmp/icons/node_modules/lucide-static/icons /opt/onyx/assets/icons/lucide/ && \
    cp -a /tmp/icons/node_modules/lucide-static/LICENSE /opt/onyx/assets/icons/lucide/ && \
    cp -a /tmp/icons/node_modules/@tabler/icons/icons /opt/onyx/assets/icons/tabler/ && \
    cp -a /tmp/icons/node_modules/@tabler/icons/LICENSE /opt/onyx/assets/icons/tabler/ && \
    rm -rf /tmp/icons /root/.npm

FROM node_source AS github_cli
ARG GH_CLI_VERSION
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*
RUN --mount=type=secret,id=build_ca_bundle,mode=0444 \
    if [ -f /run/secrets/build_ca_bundle ]; then export CURL_CA_BUNDLE=/run/secrets/build_ca_bundle; fi && \
    set -eu; \
    tarball="gh_${GH_CLI_VERSION}_linux_${TARGETARCH}.tar.gz"; \
    base="https://github.com/cli/cli/releases/download/v${GH_CLI_VERSION}"; \
    cd /tmp; \
    curl -fsSL -o "${tarball}" "${base}/${tarball}"; \
    curl -fsSL -o checksums.txt "${base}/gh_${GH_CLI_VERSION}_checksums.txt"; \
    grep " ${tarball}\$" checksums.txt | sha256sum -c -; \
    tar -xzf "${tarball}"; \
    install -m 0755 "gh_${GH_CLI_VERSION}_linux_${TARGETARCH}/bin/gh" /usr/local/bin/gh

FROM ${UV_IMAGE} AS uv_source

FROM ${PYTHON_IMAGE} AS os
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl git procps unzip zip zstd ripgrep jq \
    libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
    libcups2t64 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0t64 libnss3 libnss3-tools \
    libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 \
    xvfb xauth \
    libreoffice-core libreoffice-common libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-draw \
    poppler-utils fontconfig \
    fonts-dejavu-core fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea \
    fonts-noto-core fonts-noto-color-emoji fonts-inter fonts-montserrat fonts-lato \
    fonts-ebgaramond fonts-firacode && \
    rm -rf /var/lib/apt/lists/*

COPY backend/onyx/server/features/build/sandbox/image/install-browser.sh /tmp/install-browser.sh
RUN --mount=type=secret,id=build_ca_bundle,mode=0444 \
    if [ -f /run/secrets/build_ca_bundle ]; then export CURL_CA_BUNDLE=/run/secrets/build_ca_bundle; fi && \
    bash /tmp/install-browser.sh && rm /tmp/install-browser.sh

FROM os AS runtime
LABEL org.opencontainers.image.title="Craft Runtime"
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
COPY --from=javascript /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=javascript /opt/onyx/assets /opt/onyx/assets
COPY --from=github_cli /usr/local/bin/gh /usr/local/bin/gh
COPY --from=uv_source /uv /uvx /usr/local/bin/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    ln -s ../lib/node_modules/agent-browser/bin/agent-browser.js /usr/local/bin/agent-browser

COPY deployment/craft-runtime/requirements.txt /tmp/requirements.txt
RUN --mount=type=secret,id=build_ca_bundle,mode=0444 \
    if [ -f /run/secrets/build_ca_bundle ]; then export PIP_CERT=/run/secrets/build_ca_bundle; fi && \
    python -m venv /opt/onyx/python && \
    /opt/onyx/python/bin/python -m pip install --no-cache-dir --only-binary=:all: \
        --require-hashes -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

RUN useradd --uid 1000 --create-home --shell /bin/bash sandbox && \
    mkdir -p /workspace/sessions /workspace/managed /root/.config/gh /home/sandbox/.config/gh && \
    printf 'git_protocol: https\nprompt: disabled\n' > /home/sandbox/.config/gh/config.yml && \
    cp /home/sandbox/.config/gh/config.yml /root/.config/gh/config.yml && \
    chown -R sandbox:sandbox /home/sandbox /workspace && \
    chown root:root /workspace/managed
COPY backend/onyx/server/features/build/sandbox/image/templates/pptx/ /workspace/templates/pptx/
COPY deployment/craft-runtime/smoke-test.sh /opt/onyx/check-runtime
ARG IMAGE_VERSION
LABEL org.opencontainers.image.version="${IMAGE_VERSION}"
RUN chmod 0755 /opt/onyx/check-runtime

ENV PATH="/opt/onyx/python/bin:${PATH}" \
    NODE_PATH=/usr/local/lib/node_modules \
    AGENT_BROWSER_EXECUTABLE_PATH=/opt/chrome/chrome \
    PYTHONUNBUFFERED=1
WORKDIR /workspace
CMD ["/bin/bash"]
