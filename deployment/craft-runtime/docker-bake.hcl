variable "BASE_IMAGE_REGISTRY" {
  default = "docker.io"
}

variable "NODE_IMAGE" {
  default = "library/node:24-trixie-slim@sha256:af02d57b57719b9657a45199a79264a9437940cd55b3c7b3fc99615654f124a0"
}

variable "PYTHON_IMAGE" {
  default = "library/python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90"
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
