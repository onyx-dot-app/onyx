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
#   mkfs.xfs (xfsprogs)        makes the loop store image when the data dir has no reflink (--loop-store);
#                              only mkfs.xfs and its libraries, not the package: Debian xfsprogs
#                              depends on python3 for xfs_scrub_all, which the agent never runs
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

FROM --platform=$BUILDPLATFORM ${BASE_IMAGE_REGISTRY}/library/golang:1.27.4-alpine@sha256:0a5f7fe796599ff487605987432e7619ae45beeb2fba4c2ce0b907879932aebf AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG TARGETARCH
ARG VERSION=dev
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} \
    go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/host-agent ./cmd/host-agent

FROM ${BASE_IMAGE_REGISTRY}/library/debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4 AS xfsprogs
ARG DEBIAN_FRONTEND=noninteractive
# /out gets mkfs.xfs, the libraries it links that the base image does not have,
# and the dpkg records (status.d, as distroless images do) and copyright files
# of their packages, so image scanners still see xfsprogs and its libraries.
RUN set -eu; \
    apt-get update; \
    dpkg-query -W -f '${Package}\n' > /tmp/base-packages; \
    apt-get install -y --no-install-recommends xfsprogs; \
    mkdir -p /out/usr/sbin /out/usr/lib/x86_64-linux-gnu /out/var/lib/dpkg/status.d /out/usr/share/doc; \
    cp /usr/sbin/mkfs.xfs /out/usr/sbin/; \
    if ldd /usr/sbin/mkfs.xfs | grep -q 'not found'; then exit 1; fi; \
    pkgs=xfsprogs; \
    for lib in $(ldd /usr/sbin/mkfs.xfs | awk '$2 == "=>" { print $3 }'); do \
      pkg="$(dpkg-query -S "$(readlink -f "${lib}")" | cut -d: -f1)"; \
      if ! grep -qx "${pkg}" /tmp/base-packages; then \
        cp -L "${lib}" "/out/usr/lib/x86_64-linux-gnu/$(basename "${lib}")"; \
        pkgs="${pkgs} ${pkg}"; \
      fi; \
    done; \
    for pkg in ${pkgs}; do \
      dpkg-query -s "${pkg}" > "/out/var/lib/dpkg/status.d/${pkg}"; \
      mkdir -p "/out/usr/share/doc/${pkg}"; \
      cp "/usr/share/doc/${pkg}/copyright" "/out/usr/share/doc/${pkg}/"; \
    done

FROM ${BASE_IMAGE_REGISTRY}/library/debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4
ARG DEBIAN_FRONTEND=noninteractive
# ca-certificates: the node key registration calls the api_server (--api-server-url).
# e2fsprogs: mkfs.ext4 -d for the managed drive images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates e2fsprogs util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY --from=xfsprogs /out/ /
COPY --from=artifacts /craft-fc/ /opt/craft-fc/
COPY --from=builder /out/host-agent /usr/local/bin/host-agent
# The agent needs root, /dev/kvm, hostPID and the host cgroup tree (Helm DaemonSet).
USER root
ENTRYPOINT ["/usr/local/bin/host-agent"]
