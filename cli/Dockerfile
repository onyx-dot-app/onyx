# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to the ECR
# pull-through cache (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker
# Hub rate limits.
ARG BASE_IMAGE_REGISTRY=docker.io
FROM ${BASE_IMAGE_REGISTRY}/library/golang:1.26.4-alpine@sha256:7a3e50096189ad57c9f9f865e7e4aa8585ed1585248513dc5cda498e2f41812c AS builder

WORKDIR /app
COPY ./ .

ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -ldflags="-s -w" -o onyx-cli .
RUN mkdir -p /home/onyx/.config

FROM scratch

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder --chown=65534:65534 /home/onyx /home/onyx

COPY --from=builder /app/onyx-cli /onyx-cli

ENV HOME=/home/onyx
ENV XDG_CONFIG_HOME=/home/onyx/.config

USER 65534:65534

ENTRYPOINT ["/onyx-cli"]
