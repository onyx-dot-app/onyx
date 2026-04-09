FROM ubuntu:25.10

RUN apt-get update && apt-get install -y --no-install-recommends \
  acl \
  curl \
  git \
  sudo \
  ca-certificates \
  iptables \
  ipset \
  iproute2 \
  dnsutils \
  jq \
  zsh \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y nodejs \
  && install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

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

# Configure zsh for both root and dev — auto-activate Python venv,
# source host zshrc if bind-mounted.
RUN chsh -s /bin/zsh root && \
  for rc in /root/.zshrc /home/dev/.zshrc; do \
    echo 'if [ -f /workspace/.venv/bin/activate ]; then . /workspace/.venv/bin/activate; fi' >> "$rc"; \
    echo '[ -f /root/.zshrc.host ] && . /root/.zshrc.host' >> "$rc"; \
  done && \
  chown dev:dev /home/dev/.zshrc

# Copy init scripts
COPY init-firewall.sh init-dev-user.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/init-firewall.sh /usr/local/bin/init-dev-user.sh

# Container starts as root so postStartCommand can run init scripts.
# Terminal sessions use the dev user via remoteUser in devcontainer.json.
