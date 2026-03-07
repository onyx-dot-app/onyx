FROM golang:1.26-alpine AS builder

RUN apk add --no-cache git

WORKDIR /app
COPY ./ .

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -a -installsuffix static -o onyx-cli .

FROM scratch

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

COPY --from=builder /app/onyx-cli /onyx-cli

ENTRYPOINT ["/onyx-cli"]
