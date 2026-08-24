# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to the ECR
# pull-through cache (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker
# Hub rate limits.
ARG BASE_IMAGE_REGISTRY=docker.io

# bun + node binary sources. Pinned via the registry prefix in their own stages because buildx
# rejects variable expansion directly in `COPY --from=` -- the ARG is only expandable in a FROM.
FROM ${BASE_IMAGE_REGISTRY}/oven/bun:1@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS bun_source
FROM ${BASE_IMAGE_REGISTRY}/library/node:24.16.0-trixie-slim@sha256:05c08ce4291e9a58f59456a7985176defb12cdd42271f35ff81a3e167ea61d4c AS node_source

FROM ${BASE_IMAGE_REGISTRY}/library/ubuntu:26.04@sha256:cc925e589b7543b910fea57a240468940003fbfc0515245a495dd0ad8fe7cef1

RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  ca-certificates \
  cargo \
  cmake \
  curl \
  default-jre \
  dnsmasq \
  dnsutils \
  fd-find \
  fzf \
  git \
  gobject-introspection \
  iproute2 \
  ipset \
  iptables \
  jq \
  less \
  libayatana-appindicator3-dev \
  libgirepository1.0-dev \
  libglib2.0-dev \
  libgtk-3-dev \
  libjavascriptcoregtk-4.1-dev \
  libwebkit2gtk-4.1-dev \
  libxmlsec1-dev \
  make \
  neovim \
  nginx \
  openssh-client \
  pkg-config \
  postgresql-client \
  ripgrep \
  rust-clippy \
  rustfmt \
  socat \
  sudo \
  unzip \
  wget \
  xdg-utils \
  zsh \
  && install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends gh \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# fd-find installs as fdfind on Debian/Ubuntu — symlink to fd
RUN ln -sf "$(which fdfind)" /usr/local/bin/fd

# Install uv (Python package manager). Python deps themselves are not
# baked in — CI runs `uv sync` against the bind-mounted workspace, and
# daily dev uses their own .venv. The apt block above includes the
# system libraries `uv sync` needs to compile native extensions
# (cmake, libxmlsec1-dev, pkg-config, postgresql-client).
COPY --from=ghcr.io/astral-sh/uv:0.11.25@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9 /uv /uvx /usr/local/bin/

# Install prek (https://github.com/j178/prek) — a fast Rust reimplementation of
# pre-commit and a drop-in replacement for it. Symlinked to `pre-commit` so the
# repo's `.pre-commit-config.yaml` plus any `pre-commit ...` muscle memory and CI
# invocations work unchanged.
ARG PREK_VERSION=0.4.3
RUN set -eux; \
  case "$(dpkg --print-architecture)" in \
    amd64) PREK_TRIPLE=x86_64-unknown-linux-gnu; \
           PREK_SHA256=8a8210d64476657cac3e797afa109011d8d872c09e3a407f50c5a4dde063b381 ;; \
    arm64) PREK_TRIPLE=aarch64-unknown-linux-gnu; \
           PREK_SHA256=02e5731ce90e737bade91abef4c76c13495b9cc9290f609dfcb2e7b2a05b532e ;; \
    *) echo "unsupported arch for prek: $(dpkg --print-architecture)" >&2; exit 1 ;; \
  esac; \
  curl -fsSL -o /tmp/prek.tar.gz \
    "https://github.com/j178/prek/releases/download/v${PREK_VERSION}/prek-${PREK_TRIPLE}.tar.gz"; \
  echo "${PREK_SHA256}  /tmp/prek.tar.gz" | sha256sum -c -; \
  tar -xzf /tmp/prek.tar.gz -C /tmp; \
  install -m 0755 "/tmp/prek-${PREK_TRIPLE}/prek" /usr/local/bin/prek; \
  ln -s prek /usr/local/bin/pre-commit; \
  rm -rf /tmp/prek.tar.gz "/tmp/prek-${PREK_TRIPLE}"; \
  prek --version

# Install bun (JavaScript package manager) from the bun_source stage defined at the top.
COPY --from=bun_source /usr/local/bin/bun /usr/local/bin/bun
RUN ln -s /usr/local/bin/bun /usr/local/bin/bunx

# Install Node.js. Bun is the JS package manager, but Playwright's e2e test
# runner (web/tests/e2e) forks worker processes that require Node — running it
# under bun alone hangs the runner. Daily JS tooling (Claude Code, opencode)
# still runs under bun; Node is here only as the runtime for the test runner.
# The test runner's chromium binary is installed at test time, not baked here,
# so its version tracks web/package.json's floating @playwright/test (the
# chromium baked further down serves only the pinned Playwright MCP server).
#
# Copied from the official node image (digest-pinned in the node_source stage at the
# top, routed through BASE_IMAGE_REGISTRY) instead of fetched from nodejs.org, so a
# compromised mirror or MITM can't swap the binary and buildkit resolves the right arch
# from the manifest list. npm/npx are scripts under node_modules/npm; recreate their
# PATH symlinks since we copy the bare binary.
COPY --from=node_source /usr/local/bin/node /usr/local/bin/node
COPY --from=node_source /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
  && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
  && node --version

# Install the apt packages Playwright needs to run headless Chromium for
# the web-search open_url tool. The browser binary itself is downloaded
# from the integration test conftest's _install_playwright fixture so
# the version always matches the lockfile's playwright-python.
RUN apt-get update \
  && uvx --quiet --from playwright playwright install-deps chromium \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Give Playwright's browser cache a fixed, user-independent path. The default
# (~/.cache/ms-playwright) would be shadowed by the devcontainer's per-user
# cache volume and differ between root and dev, so revisions baked below would
# be invisible at runtime. Test-time installs (web e2e, the integration
# conftest) land their own revisions alongside the baked one.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Bake the chromium build for the Playwright MCP server. Playwright browser
# builds are revision-coupled to the playwright version that installs them, so
# resolve the exact playwright the pinned MCP bundles and install with that —
# a chromium installed by any other version would not be found. Keep the pin
# in sync with .mcp.json. World-writable so test-time installs run as the dev
# user can add their own revisions next to it.
ARG PLAYWRIGHT_MCP_VERSION=0.0.78
RUN PW_VERSION=$(npm view "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}" dependencies.playwright) \
  && npx --yes "playwright@${PW_VERSION}" install chromium \
  && chmod -R 777 /opt/ms-playwright

# Install Python 3.13 via uv into a stable, image-level path so venvs
# created in bind-mounted workspaces survive across `docker run`s.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python
RUN UV_PYTHON_BIN_DIR=/usr/local/bin uv python install 3.13 \
  && ln -s python3.13 /usr/local/bin/python3 \
  && ln -s python3.13 /usr/local/bin/python \
  && python --version

# Install the Go toolchain. `cli` pins `go 1.26.5` in its go.mod, while the older
# `tools/ods` requirement remains compatible. The golangci-lint pre-commit hook builds
# both modules against this version — keep it in sync with the hook and with GO_VERSION
# in .github/workflows/pr-golang-tests.yml.
#
# Fetched from go.dev with a pinned per-arch checksum (same shape as the prek install
# above) rather than copied out of the official golang image: base images here route
# through the ECR pull-through cache, which only populates on tag-based pulls, so a
# `golang:...@sha256:...` stage fails to resolve until something has already pulled that
# exact digest by tag. The sha256 pin is what defeats a compromised mirror or MITM, so
# nothing is given up by not going through a registry.
#
# Module and build caches are not baked in; they live in the dev user's home
# (see .devcontainer/zshrc).
ARG GO_VERSION=1.26.5
RUN set -eux; \
  case "$(dpkg --print-architecture)" in \
    amd64) GO_ARCH=amd64; \
           GO_SHA256=5c2c3b16caefa1d968a94c1daca04a7ca301a496d9b086e17ad77bb81393f053 ;; \
    arm64) GO_ARCH=arm64; \
           GO_SHA256=fe4789e92b1f33358680864bbe8704289e7bb5fc207d80623c308935bd696d49 ;; \
    *) echo "unsupported arch for go: $(dpkg --print-architecture)" >&2; exit 1 ;; \
  esac; \
  curl -fsSL -o /tmp/go.tar.gz \
    "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz"; \
  echo "${GO_SHA256}  /tmp/go.tar.gz" | sha256sum -c -; \
  tar -C /usr/local -xzf /tmp/go.tar.gz; \
  rm -f /tmp/go.tar.gz
ENV PATH=/usr/local/go/bin:$PATH
RUN go version

# Create non-root dev user with passwordless sudo
RUN useradd -m -s /bin/zsh dev && \
  echo "dev ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/dev && \
  chmod 0440 /etc/sudoers.d/dev

ENV DEVCONTAINER=true

RUN mkdir -p /workspace && \
  chown -R dev:dev /workspace

# Mark /workspace as safe for git regardless of host/container UID mismatch.
# Daily dev sidesteps "dubious ownership" via init-dev-user.sh (UID remap or
# rootless-root). One-shot `docker run` uses (e.g. CI) skip postStartCommand
# entirely, so we set this system-wide.
RUN git config --system --add safe.directory /workspace

WORKDIR /workspace

# Install Claude Code
ARG CLAUDE_CODE_VERSION=latest
RUN BUN_INSTALL=/usr/local bun install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Install opencode CLI for Craft agent functionality. Like Claude Code, it
# runs under bun (the Node.js install above exists only for Playwright's runner).
ARG OPENCODE_VERSION=latest
RUN BUN_INSTALL=/usr/local bun install -g opencode-ai@${OPENCODE_VERSION}

# Configure zsh — source the repo-local zshrc so shell customization
# doesn't require an image rebuild.
RUN chsh -s /bin/zsh root && \
  for rc in /root/.zshrc /home/dev/.zshrc; do \
    echo '[ -f /workspace/.devcontainer/zshrc ] && . /workspace/.devcontainer/zshrc' >> "$rc"; \
  done && \
  chown dev:dev /home/dev/.zshrc

# Pre-seed GitHub's SSH host keys so git-over-SSH never prompts.  Keys are
# pinned in-repo (verified against the fingerprints GitHub publishes at
# https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
# rather than fetched at build time, so a compromised build-time network can't
# inject a rogue key.
COPY github_known_hosts /etc/ssh/ssh_known_hosts
RUN chmod 644 /etc/ssh/ssh_known_hosts
