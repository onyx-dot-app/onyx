variable "REPOSITORY" {
  default = "onyxdotapp/onyx-integration"
}

variable "TAG" {
  default = "latest"
}

target "backend" {
  context    = "."
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "integration" {
  context    = "."
  dockerfile = "tests/integration/Dockerfile"
  platforms  = ["linux/amd64"]

  // Provide the base image via build context from the backend target
  contexts = {
    base = "target:backend"
  }

  cache-from = ["type=registry,ref=${REPOSITORY}:integration-test-backend-cache"]
  cache-to   = ["type=registry,ref=${REPOSITORY}:integration-test-backend-cache,mode=max"]

  tags      = ["${REPOSITORY}:${TAG}"]
}
