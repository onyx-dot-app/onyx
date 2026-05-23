# Brewfile for Onyx local development.
#
# Install with:
#   brew bundle
#
# Currently scoped to the Tilt + k3d local-cluster workflow; see
# docs/dev/local-cluster.md.

# Local Kubernetes cluster (k3s-in-Docker) used by the local-cluster workflow.
brew "k3d"

# Tilt orchestrates Helm install + hot-reload of source into running pods.
brew "tilt"

# Standard CLI prereqs.
brew "kubectl"
brew "helm"
brew "jq"

# direnv auto-loads `.envrc` at the repo root, scoping KUBECONFIG to the
# local k3d cluster so commands from inside the repo can't accidentally
# hit prod/staging. After install, add `eval "$(direnv hook zsh)"` (or
# bash) to your shell rc, then `direnv allow .` once per checkout.
brew "direnv"

# Recommended log + pod-exec tools used alongside the Tilt UI.
brew "k9s"
brew "stern"
