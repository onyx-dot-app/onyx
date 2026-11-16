variable "BASE_IMAGE_REGISTRY" {
  default = "docker.io"
}

variable "NODE_IMAGE" {
  default = "library/node:24-trixie-slim@sha256:0820eaa85e07d0490446dd01d14707e17e6108a36988cf374899cd057eb3812d"
}

variable "PYTHON_IMAGE" {
  default = "library/python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90"
}

variable "UV_IMAGE" {
  default = "ghcr.io/astral-sh/uv:0.11.25@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9"
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
  default = "0.35.3"
}

variable "LUCIDE_VERSION" {
  default = "1.24.0"
}

variable "TABLER_VERSION" {
  default = "3.44.0"
}

variable "GH_CLI_VERSION" {
  default = "2.94.0"
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
