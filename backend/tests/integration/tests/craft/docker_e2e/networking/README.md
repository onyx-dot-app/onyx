Run this suite against an existing Craft Docker Compose deployment through its frontend.
The deployment must allow registration and have a configured LLM provider.
The host needs Docker access to the same daemon used by the deployment.

Run once with the default IPv4 sandbox bridge, then with the documented IPv6-only bridge:

```sh
SANDBOX_TEST_FRONTEND_URL=http://localhost:3108 \
SANDBOX_TEST_IP_FAMILY=ipv4 \
uv run pytest backend/tests/integration/tests/craft/docker_e2e/networking -v

SANDBOX_TEST_FRONTEND_URL=http://localhost:3108 \
SANDBOX_TEST_IP_FAMILY=ipv6 \
uv run pytest backend/tests/integration/tests/craft/docker_e2e/networking -v
```

These settings describe the deployment under test; they do not configure its network.
The frontend URL is its origin, without `/api`. Missing settings skip the suite;
partial settings fail. `SANDBOX_TEST_PUBLIC_URL` can select another reachable HTTPS origin.

The suite creates a user and session. It deletes its session and sandbox container afterward.
The test user and sandbox volume remain. It does not reset local databases or workers.

Checks cover bridge addresses, listener selection, agent privileges, verified HTTPS,
API credential injection, HTTP/CONNECT destination rejection, direct egress isolation,
unidentified-client rejection, uploads, and generated Next.js previews.
