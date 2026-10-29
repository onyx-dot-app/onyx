# Craft Docker sandbox backend: local development

Use this guide when you change the Docker sandbox path (`SANDBOX_BACKEND=docker`),
the sandbox egress proxy (`backend/onyx/sandbox_proxy/`), or
`deployment/docker_compose/docker-compose.craft.yml`.
For other Craft work, use the kind workflow in
[`deployment/helm/dev/README.md`](../../../../../../../deployment/helm/dev/README.md).
It is faster for general Craft iteration.

## Prerequisites

- Docker with at least 8 CPU and 16 GB.
- The [CONTRIBUTING.md](../../../../../../../CONTRIBUTING.md) prerequisites, including `.venv` and `.vscode/.env`.
- A local sandbox image. Kubernetes and Compose use the same image, so the
  `onyxdotapp/sandbox:dev` image that `make craft-sandbox-image` builds also works here:

  ```bash
  docker build -t onyxdotapp/sandbox:dev backend/onyx/server/features/build/sandbox/image
  ```

Create the external resources that the Craft overlay expects:

```bash
docker network create onyx_craft_sandbox
docker volume create sandbox_proxy_ca
```

## Full stack in Compose

This is closest to a self-hosted Craft install. Use it for end-to-end smoke tests.
Craft requires a Business or Enterprise license.

```bash
cd deployment/docker_compose
ENABLE_CRAFT=true SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev \
docker compose -f docker-compose.yml -f docker-compose.craft.yml --env-file env.template up -d --wait
docker compose -f docker-compose.yml -f docker-compose.craft.yml logs -f sandbox-proxy
```

The proxy is mandatory for the Docker backend. Every sandbox runs
`firewall-init.sh` and sends egress through `sandbox-proxy`.
`DockerSandboxManager` fails at startup if `SANDBOX_PROXY_HOST` is empty.
The overlay uses `${SANDBOX_PROXY_HOST-sandbox-proxy}` (single dash) so an explicit
empty value reaches that check instead of the default.

To test only the API server with an unreleased backend, set `ONYX_BACKEND_IMAGE`.
Do not set `IMAGE_TAG` to a local tag: it applies to every service image.
When you recreate services that use a local-only image, add `--no-build`.
Otherwise Compose can try to build from a context path that does not resolve.

## Debug the proxy locally

1. Start the infrastructure and write its ports to `.vscode/.env`:

   ```bash
   ods compose dev --infra
   ods env
   ```

2. Run the proxy on port 8888, because the local API server uses 8080.
   Its health port stays 8081. The CA store path `/var/lib/sandbox-proxy/ca` is
   fixed (`SANDBOX_PROXY_CA_VOLUME_PATH`), so create it and make it writable first.
   The default mitmproxy directory is under `/var/run`, so set a writable one.

   ```bash
   sudo mkdir -p /var/lib/sandbox-proxy/ca && sudo chown "$USER" /var/lib/sandbox-proxy/ca
   PYTHONPATH=./backend SANDBOX_BACKEND=docker SANDBOX_PROXY_LISTEN_PORT=8888 \
   SANDBOX_PROXY_MITM_CONFDIR=/tmp/sandbox-proxy-mitm \
     uv run --env-file .vscode/.env python -m onyx.sandbox_proxy.server
   ```

   Sandboxes read the CA from the `sandbox_proxy_ca` volume, not from the host
   directory. After the proxy logs `Persisted proxy CA`, copy only the certificate
   into the volume. This replaces the CA of the Compose stack, so remove the volume
   before you use the Compose stack again.

   ```bash
   docker run --rm -i -v sandbox_proxy_ca:/sandbox-ca alpine \
     sh -c 'rm -f /sandbox-ca/ca.key && cat > /sandbox-ca/ca.crt && chmod 644 /sandbox-ca/ca.crt' \
     < /var/lib/sandbox-proxy/ca/ca.crt
   ```

3. Run the API server against that proxy:

   ```bash
   PYTHONPATH=./backend ENABLE_CRAFT=true SANDBOX_BACKEND=docker \
   SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev \
   SANDBOX_PROXY_HOST=host.docker.internal SANDBOX_PROXY_PORT=8888 \
     uv run --env-file .vscode/.env uvicorn onyx.main:app --host 0.0.0.0 --port 8080
   ```

   `host.docker.internal` works on Docker Desktop. Linux sandboxes do not get a
   `host-gateway` alias, so use the full Compose stack on Linux.

4. Start a Craft session and trigger a gated action. Set breakpoints in the proxy
   (`addons/gate.py`, `request_evaluator.py`, `sandbox_identity/docker.py`).

## Smoke checks inside a sandbox

```bash
docker exec -it sandbox-<id8> bash
curl -v https://example.com 2>&1 | grep -E '(Issuer|HTTP/)'   # succeeds; proxy CA signs the leaf
curl --noproxy '*' --max-time 5 https://example.com            # blocked by iptables
nslookup example.com                                           # DNS is closed
getpcaps $$                                                    # no capabilities
```

## Teardown

```bash
cd deployment/docker_compose
docker compose -f docker-compose.yml -f docker-compose.craft.yml down
docker volume rm sandbox_proxy_ca                                                # optional: new CA on next start
docker volume ls --filter "name=onyx-craft-sandbox-" -q | xargs -r docker volume rm  # optional: sandbox state
```

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| `firewall-init.sh: FATAL: CA source ... not present` | The proxy has not written its CA yet. Wait for the proxy to log `Persisted proxy CA`, then provision again. |
| `could not resolve proxy host sandbox-proxy` | The sandbox or proxy is not on `onyx_craft_sandbox`. Check with `docker inspect sandbox-<id8>`. |
| All egress returns 403 `unidentified_sandbox` | The proxy cannot see the sandbox's `onyx.app/*` labels. The manager did not run with `SANDBOX_BACKEND=docker`. |
| `No such volume: sandbox_proxy_ca` | Run `docker volume create sandbox_proxy_ca`. |
| Egress fails after a proxy restart | The proxy got a new bridge IP. The sandbox iptables rule pins the old IP. Provision the sandbox again. |
| A sandbox lacks env vars that new code injects | Existing containers keep their creation-time env. Remove the container and its `onyx-craft-sandbox-<id8>` volume. |
| OpenSearch reports a `flood-stage watermark` block | The Docker VM disk is full. Run `docker builder prune` and remove unused images. The block clears when usage drops. |
