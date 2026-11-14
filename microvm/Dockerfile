# Craft Firecracker host agent image, onyxdotapp/craft-fc-host-agent.
#
# Build context: this directory (microvm/). linux/amd64 only: the artifacts are x86_64.
#
# Contents:
#   /usr/local/bin/host-agent  static Go build of cmd/host-agent (the entrypoint)
#   /opt/craft-fc/             vmlinux, firecracker, jailer, licenses: the default --artifacts-dir,
#                              copied from onyxdotapp/craft-fc-artifacts (deployment/craft-fc)
#   nsenter (util-linux)       the agent starts each VM with
#                              `nsenter -t 1 -m -- systemd-run ...`, so systemd-run and systemctl
#                              come from the host, not from this image (setns into the host
#                              mount namespace also sets the root and cwd to the host's root)
#   mkfs.ext4 (e2fsprogs)      `mkfs.ext4 -d` builds the read-only managed (skills) drive images
#   mkfs.xfs (xfsprogs)        makes the loop store image when the data dir has no reflink (--loop-store)
#
# Local build while the artifacts image is not published, from the repo root:
#   docker buildx build --platform linux/amd64 -f deployment/craft-fc/Dockerfile.artifacts \
#     --target artifacts --output type=local,dest=/tmp/craft-fc-artifacts deployment/craft-fc
#   docker buildx build --platform linux/amd64 --build-context artifacts=/tmp/craft-fc-artifacts \
#     -t local/craft-fc-host-agent:dev --load microvm
#   bash microvm/check-image.sh local/craft-fc-host-agent:dev

# Registry prefix for base images. CI overrides it with the ECR pull-through cache.
ARG BASE_IMAGE_REGISTRY=docker.io
# Tag of onyxdotapp/craft-fc-artifacts. It must match the ARG values in
# deployment/craft-fc/Dockerfile.artifacts and the SHA256 pins in internal/binaries.
ARG ARTIFACTS_TAG=6.18.25-57.115-fc1.17.0
ARG ARTIFACTS_IMAGE=${BASE_IMAGE_REGISTRY}/onyxdotapp/craft-fc-artifacts:${ARTIFACTS_TAG}

# A named build context "artifacts" (a local Dockerfile.artifacts build) replaces this stage.
FROM ${ARTIFACTS_IMAGE} AS artifacts

FROM --platform=$BUILDPLATFORM ${BASE_IMAGE_REGISTRY}/library/golang:1.27.1-alpine@sha256:8a5910f31396cd4d89662f56c68b3ae31d374308270a1c3bd96672ee5ed43414 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG TARGETARCH
ARG VERSION=dev
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} \
    go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/host-agent ./cmd/host-agent

FROM ${BASE_IMAGE_REGISTRY}/library/debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4
ARG DEBIAN_FRONTEND=noninteractive
# ca-certificates: the node key registration calls the api_server (--api-server-url).
# e2fsprogs: mkfs.ext4 -d for the managed drive images. xfsprogs: the loop store.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates e2fsprogs util-linux xfsprogs \
    && rm -rf /var/lib/apt/lists/*
COPY --from=artifacts /craft-fc/ /opt/craft-fc/
COPY --from=builder /out/host-agent /usr/local/bin/host-agent
# The agent needs root, /dev/kvm, hostPID and the host cgroup tree (Helm DaemonSet).
USER root
ENTRYPOINT ["/usr/local/bin/host-agent"]
