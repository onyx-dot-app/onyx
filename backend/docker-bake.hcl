group "default" {
  targets = ["backend", "model-server", "integration"]
}

variable "BACKEND_REPOSITORY" {
  default = "onyxdotapp/onyx-backend"
}

variable "MODEL_SERVER_REPOSITORY" {
  default = "onyxdotapp/onyx-model-server"
}

variable "INTEGRATION_REPOSITORY" {
  default = "onyxdotapp/onyx-integration"
}

variable "TAG" {
  default = "latest"
}

target "backend" {
  context    = "."
  dockerfile = "Dockerfile"

  cache-from = ["type=registry,ref=${BACKEND_REPOSITORY}:latest"]
  cache-to   = ["type=inline"]

  tags      = ["${BACKEND_REPOSITORY}:${TAG}"]
}

target "model-server" {
  context = "."

  dockerfile = "Dockerfile"

  cache-from = ["type=registry,ref=${MODEL_SERVER_REPOSITORY}:latest"]
  cache-to   = ["type=inline"]

  tags      = ["${MODEL_SERVER_REPOSITORY}:${TAG}"]
}

target "integration" {
  context    = "."
  dockerfile = "tests/integration/Dockerfile"

  // Provide the base image via build context from the backend target
  contexts = {
    base = "target:backend"
  }

  tags      = ["${INTEGRATION_REPOSITORY}:${TAG}"]
}
