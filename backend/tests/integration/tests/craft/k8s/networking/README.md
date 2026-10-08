These tests exercise an existing single-stack Kubernetes deployment through its frontend.
They create a test user and session, then delete the session and its sandbox.
The test user remains registered. Local databases and workers are not used or reset.

Deploy the chart, backend, and sandbox images under test before running this suite.
The deployment must support registration and Craft provisioning, with a configured LLM provider.
Configure proxy internal CIDRs for all cluster and service networks, including global IPv6 ranges.
The host needs `kubectl` access, and the sandbox needs public HTTPS access.

Run once per IP family:

```sh
SANDBOX_TEST_FRONTEND_URL=http://localhost:3104 \
SANDBOX_TEST_KUBE_CONTEXT=kind-onyx-ipv4 \
SANDBOX_TEST_IP_FAMILY=ipv4 \
uv run pytest backend/tests/integration/tests/craft/k8s/networking -v

SANDBOX_TEST_FRONTEND_URL=http://localhost:3106 \
SANDBOX_TEST_KUBE_CONTEXT=kind-onyx-ipv6 \
SANDBOX_TEST_IP_FAMILY=ipv6 \
uv run pytest backend/tests/integration/tests/craft/k8s/networking -v
```

The frontend URL is its origin, without `/api`. Existing API Managers route through that frontend.
Every `kubectl` call names its context; the current context remains unchanged.
Without these settings, the suite skips. Partial settings fail.

Optional settings:

- `SANDBOX_TEST_NAMESPACE`: sandbox namespace, default `onyx-sandboxes`.
- `SANDBOX_TEST_APP_NAMESPACE`: proxy namespace, default `onyx`.
- `SANDBOX_TEST_PUBLIC_URL`: reachable public HTTPS page, default `https://example.com`.
- `SANDBOX_TEST_FLUSH_NEIGHBORS=true`: also test IPv6 connectivity with an empty neighbor cache.
  This requires a local kind cluster, Docker access, and privileged exec in its node container.
  It clears only the test sandbox's neighbor cache. Other deployments skip this test.

The suite checks single-stack pod addresses, public HTTPS, injected API credentials,
the exact API exception, internal destination rejection for HTTP and CONNECT,
direct egress isolation, unidentified-client rejection, signed uploads, and generated Next.js previews.
Model turns and approval interactions have separate Craft suites.
