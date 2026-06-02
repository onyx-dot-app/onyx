# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to the ECR
# pull-through cache (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker
# Hub rate limits.
ARG BASE_IMAGE_REGISTRY=docker.io

# bun binary source. Pinned via the registry prefix in its own stage because buildx
# rejects variable expansion directly in `COPY --from=` -- the ARG is only expandable in a FROM.
FROM ${BASE_IMAGE_REGISTRY}/oven/bun:1@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS bun_source

FROM ${BASE_IMAGE_REGISTRY}/library/ubuntu:26.04@sha256:cc925e589b7543b910fea57a240468940003fbfc0515245a495dd0ad8fe7cef1

RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  ca-certificates \
  cmake \
  curl \
  default-jre \
  dnsmasq \
  dnsutils \
  fd-find \
  fzf \
  git \
  iproute2 \
  ipset \
  iptables \
  jq \
  less \
  libxmlsec1-dev \
  make \
  neovim \
  openssh-client \
  pkg-config \
  postgresql-client \
  python3-venv \
  ripgrep \
  socat \
  sudo \
  supervisor \
  unzip \
  wget \
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
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install bun (JavaScript package manager) from the bun_source stage defined at the top.
COPY --from=bun_source /usr/local/bin/bun /usr/local/bin/bun
RUN ln -s /usr/local/bin/bun /usr/local/bin/bunx

# Install Node.js. Bun is the JS package manager, but Playwright's e2e test
# runner (web/tests/e2e) forks worker processes that require Node — running it
# under bun alone hangs the runner. Daily JS tooling (Claude Code, opencode)
# still runs under bun; Node is here only as the runtime for the test runner.
# The chromium browser binary is installed at test time (web global-setup), not
# baked here, so its version tracks web/package.json's floating @playwright/test.
#
# Copied from the official node image (digest-pinned like bun above) instead of
# fetched from nodejs.org, so a compromised mirror or MITM can't swap the binary
# and buildkit resolves the right arch from the manifest list. Keep both COPY
# refs in sync when bumping the version. npm/npx are scripts under
# node_modules/npm; recreate their PATH symlinks since we copy the bare binary.
COPY --from=node:24.16.0-trixie-slim@sha256:05c08ce4291e9a58f59456a7985176defb12cdd42271f35ff81a3e167ea61d4c /usr/local/bin/node /usr/local/bin/node
COPY --from=node:24.16.0-trixie-slim@sha256:05c08ce4291e9a58f59456a7985176defb12cdd42271f35ff81a3e167ea61d4c /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
  && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
  && node --version

# Install the apt packages Playwright needs to run headless Chromium for
# the web-search open_url tool. The browser binary itself is downloaded
# from the integration test conftest's _install_playwright fixture so
# the version always matches the lockfile's playwright-python.
#
# Playwright doesn't ship Chromium builds for Ubuntu 26.04 yet, so spoof
# the host platform to the binary-compatible Ubuntu 24.04 build. Arch
# is detected from dpkg so both arm64 CI runners and x64 dev machines
# work; we don't bake the override into ENV because that would leak
# into interactive dev shells where it might mask real problems.
RUN apt-get update \
  && PW_ARCH=$(case $(dpkg --print-architecture) in amd64) echo x64;; arm64) echo arm64;; esac) \
  && PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-${PW_ARCH} \
       uvx --quiet --from playwright playwright install-deps chromium \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python 3.11 via uv into a stable, image-level path so venvs
# created in bind-mounted workspaces survive across `docker run`s.
# Ubuntu 26.04's system Python is 3.14, but onnxruntime only ships
# cp311–cp313 wheels; the repo pins 3.11 via .python-version.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python
RUN uv python install 3.11

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
