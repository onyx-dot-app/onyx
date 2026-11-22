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

## Change the proxy

Run the proxy in Compose, not on the host. The proxy identifies each sandbox by
the request source IP, which must be the container IP on `onyx_craft_sandbox`
(`backend/onyx/sandbox_proxy/sandbox_identity/docker.py`). A proxy on the host
gets the Docker gateway address instead, so every request fails with
`403 unidentified_sandbox`.

To test local backend or proxy code, build a backend image and start the stack
with it. `ONYX_BACKEND_IMAGE` applies to every backend service, including
`sandbox-proxy`. Do not set `IMAGE_TAG` to a local tag: it also applies to the
web server and other images. Add `--no-build`, because Compose otherwise
rebuilds the services that have a `build` section.

```bash
docker build -t onyxdotapp/onyx-backend:dev backend
cd deployment/docker_compose
ONYX_BACKEND_IMAGE=onyxdotapp/onyx-backend:dev ENABLE_CRAFT=true \
SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev \
docker compose -f docker-compose.yml -f docker-compose.craft.yml --env-file env.template up -d --no-build --wait
```

A recreated proxy can get a new bridge IP, so provision sandboxes again after
each restart. The gate logs each identity failure as `identity_unknown_sandbox`
or `identity_missing_src_ip` (`backend/onyx/sandbox_proxy/addons/gate.py`).

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
| `firewall-init.sh: FATAL: CA source ... not present` | The proxy has not written its CA yet. Wait for the proxy to log `CA bootstrapped`, then provision again. |
| `could not resolve proxy host sandbox-proxy` | The sandbox or proxy is not on `onyx_craft_sandbox`. Check with `docker inspect sandbox-<id8>`. |
| All egress returns 403 `unidentified_sandbox` | The proxy cannot see the sandbox's `onyx.app/*` labels. The manager did not run with `SANDBOX_BACKEND=docker`. |
| `No such volume: sandbox_proxy_ca` | Run `docker volume create sandbox_proxy_ca`. |
| Egress fails after a proxy restart | The proxy got a new bridge IP. The sandbox iptables rule pins the old IP. Provision the sandbox again. |
| A sandbox lacks env vars that new code injects | Existing containers keep their creation-time env. Remove the container and its `onyx-craft-sandbox-<id8>` volume. |
| OpenSearch reports a `flood-stage watermark` block | The Docker VM disk is full. Run `docker builder prune` and remove unused images. The block clears when usage drops. |
