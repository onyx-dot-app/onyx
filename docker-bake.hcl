group "default" {
  targets = ["backend", "model-server", "web"]
}

variable "BACKEND_REPOSITORY" {
  default = "onyxdotapp/onyx-backend"
}

variable "WEB_SERVER_REPOSITORY" {
  default = "onyxdotapp/onyx-web-server"
}

variable "MODEL_SERVER_REPOSITORY" {
  default = "onyxdotapp/onyx-model-server"
}

variable "INTEGRATION_REPOSITORY" {
  default = "onyxdotapp/onyx-integration"
}

variable "CLI_REPOSITORY" {
  default = "onyxdotapp/onyx-cli"
}

variable "DEVCONTAINER_REPOSITORY" {
  default = "onyxdotapp/onyx-devcontainer"
}

variable "TAG" {
  default = "latest"
}

target "backend" {
  context    = "backend"
  dockerfile = "Dockerfile"

  cache-from = [
    "type=registry,ref=${BACKEND_REPOSITORY}:latest",
    "type=registry,ref=${BACKEND_REPOSITORY}:edge",
  ]
  cache-to   = ["type=inline"]

  tags      = ["${BACKEND_REPOSITORY}:${TAG}"]
}

target "web" {
  context    = "web"
  dockerfile = "Dockerfile"

  cache-from = [
    "type=registry,ref=${WEB_SERVER_REPOSITORY}:latest",
    "type=registry,ref=${WEB_SERVER_REPOSITORY}:edge",
  ]
  cache-to   = ["type=inline"]

  tags      = ["${WEB_SERVER_REPOSITORY}:${TAG}"]
}

target "model-server" {
  context = "backend"

  dockerfile = "Dockerfile.model_server"

  cache-from = [
    "type=registry,ref=${MODEL_SERVER_REPOSITORY}:latest",
    "type=registry,ref=${MODEL_SERVER_REPOSITORY}:edge",
  ]
  cache-to   = ["type=inline"]

  tags      = ["${MODEL_SERVER_REPOSITORY}:${TAG}"]
}

target "integration" {
  context    = "backend"
  dockerfile = "tests/integration/Dockerfile"

  // Provide the base image via build context from the backend target
  contexts = {
    base = "target:backend"
  }

  tags      = ["${INTEGRATION_REPOSITORY}:${TAG}"]
}

target "cli" {
  context    = "cli"
  dockerfile = "Dockerfile"

  cache-from = [
    "type=registry,ref=${CLI_REPOSITORY}:latest",
    "type=registry,ref=${CLI_REPOSITORY}:edge",
  ]
  cache-to   = ["type=inline"]

  tags      = ["${CLI_REPOSITORY}:${TAG}"]
}

target "devcontainer" {
  context    = ".devcontainer"
  dockerfile = "Dockerfile"

  cache-from = [
    "type=registry,ref=${DEVCONTAINER_REPOSITORY}:latest",
    "type=registry,ref=${DEVCONTAINER_REPOSITORY}:edge",
  ]
  cache-to   = ["type=inline"]

  tags      = ["${DEVCONTAINER_REPOSITORY}:${TAG}"]
}
