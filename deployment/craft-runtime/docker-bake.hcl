variable "BASE_IMAGE_REGISTRY" {
  default = "docker.io"
}

variable "NODE_IMAGE" {
  default = "library/node:24-trixie-slim@sha256:4d00acb4bcc42c454c4eb801526f7ad7f772ea3bd4fd168c5cc2e384abcbb9d4"
}

variable "PYTHON_IMAGE" {
  default = "library/python:3.13-slim@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50"
}

variable "UV_IMAGE" {
  default = "ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85"
}

variable "NPM_VERSION" {
  default = "11.17.0"
}

variable "AGENT_BROWSER_VERSION" {
  default = "0.31.1"
}

variable "PPTXGENJS_VERSION" {
  default = "4.0.1"
}

variable "SHARP_VERSION" {
  default = "0.35.5"
}

variable "LUCIDE_VERSION" {
  default = "1.24.0"
}

variable "TABLER_VERSION" {
  default = "3.44.0"
}

variable "GH_CLI_VERSION" {
  default = "2.102.0"
}

variable "IMAGE_VERSION" {
  default = "dev"
}

variable "REGISTRY_IMAGE" {
  default = "onyxdotapp/craft-runtime"
}

variable "TAG" {
  default = "dev"
}

group "default" {
  targets = ["runtime"]
}

target "runtime" {
  context    = "."
  dockerfile = "deployment/craft-runtime/Dockerfile"
  target     = "runtime"
  platforms  = ["linux/amd64"]
  tags       = ["${REGISTRY_IMAGE}:${TAG}"]

  args = {
    NODE_IMAGE            = "${BASE_IMAGE_REGISTRY}/${NODE_IMAGE}"
    PYTHON_IMAGE          = "${BASE_IMAGE_REGISTRY}/${PYTHON_IMAGE}"
    UV_IMAGE              = UV_IMAGE
    NPM_VERSION           = NPM_VERSION
    AGENT_BROWSER_VERSION = AGENT_BROWSER_VERSION
    PPTXGENJS_VERSION      = PPTXGENJS_VERSION
    SHARP_VERSION         = SHARP_VERSION
    LUCIDE_VERSION        = LUCIDE_VERSION
    TABLER_VERSION        = TABLER_VERSION
    GH_CLI_VERSION        = GH_CLI_VERSION
    IMAGE_VERSION         = IMAGE_VERSION
  }
}
