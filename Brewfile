# Brewfile for Onyx local development.
#
# Install with:
#   brew bundle
#
# Currently scoped to the Craft Tilt local-dev path; see
# docs/dev/craft-tilt-dev.md.

# Local Kubernetes cluster (k3s-in-Docker) used by the Craft dev workflow.
brew "k3d"

# Tilt orchestrates Helm install + hot-reload of backend code into running
# pods.
brew "tilt"

# kubectl + helm are CLI prereqs for any K8s dev path.
brew "kubectl"
brew "helm"

# Recommended log + pod-exec tools used alongside the Tilt UI.
brew "k9s"
brew "stern"
