group "default" {
  targets = ["backend", "integration"]
}

variable "REPOSITORY" {
  default = "onyxdotapp/onyx-backend"
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

  cache-from = ["type=registry,ref=${REPOSITORY}:latest"]
  cache-to   = ["type=inline"]

  tags      = ["${REPOSITORY}:${TAG}"]
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
