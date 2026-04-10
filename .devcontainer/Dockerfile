FROM ubuntu:26.04@sha256:cc925e589b7543b910fea57a240468940003fbfc0515245a495dd0ad8fe7cef1

RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  fd-find \
  fzf \
  git \
  jq \
  less \
  make \
  neovim \
  openssh-client \
  python3-venv \
  ripgrep \
  sudo \
  ca-certificates \
  iptables \
  ipset \
  iproute2 \
  dnsutils \
  unzip \
  wget \
  zsh \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y nodejs \
  && install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
  && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin gh \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# fd-find installs as fdfind on Debian/Ubuntu — symlink to fd
RUN ln -sf "$(which fdfind)" /usr/local/bin/fd

# Install uv (Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Create non-root dev user with passwordless sudo
RUN useradd -m -s /bin/zsh dev && \
  echo "dev ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/dev && \
  chmod 0440 /etc/sudoers.d/dev

ENV DEVCONTAINER=true

RUN mkdir -p /workspace && \
  chown -R dev:dev /workspace

WORKDIR /workspace

# Install Claude Code
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Configure zsh — source the repo-local zshrc so shell customization
# doesn't require an image rebuild.
RUN chsh -s /bin/zsh root && \
  for rc in /root/.zshrc /home/dev/.zshrc; do \
    echo '[ -f /workspace/.devcontainer/zshrc ] && . /workspace/.devcontainer/zshrc' >> "$rc"; \
  done && \
  chown dev:dev /home/dev/.zshrc
