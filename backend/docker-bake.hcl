variable "REGISTRY" {
  default = "onyxdotapp"
}

variable "TAG" {
  default = "latest"
}

target "backend" {
  context    = "."
  dockerfile = "Dockerfile"
}

target "integration" {
  context    = "."
  dockerfile = "tests/integration/Dockerfile"

  // Provide the base image via build context from the backend target
  contexts = {
    base = "target:backend"
  }

  tags      = ["${REGISTRY}/integration-test-onyx-integration:${TAG}"]
}
