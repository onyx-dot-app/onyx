# Pi worker security review

This review covers the shared Pi chat worker and its credential boundary.
It does not establish that the complete Onyx deployment is secure.
The fixes described here require matching API and worker versions.
They are local, uncommitted changes. They have not been deployed to craft-dev.

## Trust model

Tenant model settings are untrusted configuration, including credentials, headers,
and custom provider URLs. They must not select local files, executable credential
providers, another tenant's credentials, or the worker's cloud identity.

The Python API and TypeScript worker are trusted application services.
A worker holds plaintext credentials and prompts in memory during execution.
Many tenants share one process, user ID, and internal API service token.
Run-local objects prevent accidental credential mixing; they do not isolate
memory from compromised worker code. Tool execution remains in the Python API.

## Confirmed problems

The previous Gemini Vertex adapter wrote credential JSON to temporary files.
Permissions restricted access to the worker user, which all concurrent runs shared.
Normal cleanup did not cover abrupt process termination.

Both Google adapters accepted general Google credential configurations.
Google's authentication library supports external-account sources backed by files
or URLs. It can forward source contents to a configured token endpoint.

A controlled reproduction used only a loopback server and synthetic tokens.
The installed library fetched the supplied `credential_source.url` and forwarded
its response to the supplied `token_url`. Source inspection also confirmed that
file sources call `fs.readFile`; no real credential files were read during testing.
Changing only the temporary-file implementation would not fix this configuration
execution path.

Pi's environment lookup also fell back to process environment variables when a
run supplied its own environment. Missing tenant credentials could therefore reach
ambient authentication paths. The Helm worker inherited the API service account,
and worker deployments received unnecessary state Redis configuration.

## Changes

- [Google authentication](src/google-auth.ts) constructs run-local JWT or access-token
  clients in memory. It accepts service-account key fields instead of general SDK
  credential configurations. External-account and impersonation configurations are
  rejected; credential-source, endpoint, and other extra fields are not passed to
  the SDK. Credential parsing errors omit supplied values.
- [Provider authentication](src/provider-auth.ts) builds an explicit allowlist of
  provider options. Tenant configuration is not copied into an SDK environment.
  The [pinned Pi patch](patches/) makes scoped environment lookup authoritative.
  Incomplete credentials fail before an SDK can consult ambient credentials.
- Workload identity defaults off. It requires operator opt-in, explicit provider
  selection, and host authorization. The API does not grant that authorization
  in multitenant mode. An approved single-tenant deployment must use a dedicated,
  least-privileged cloud identity.
- [Input storage](../backend/onyx/chat/pi/input_storage.py) separates connection
  credentials from ordinary chat state. API keys, provider settings/options, and
  tool/MCP headers (including the request copy) enter the credential blob.
  Provider extension maps can contain credentials under arbitrary keys, so they
  stay together. Ordinary chat inputs retain JSON serialization and compression.
  Both parts share one Redis record for atomic admission, expiration, and cleanup.
- [Shared cache values](../backend/onyx/cache/encryption.py) reuse Onyx's existing
  edition-aware encryption functions. CE does not encrypt. EE encrypts with its
  configured `ENCRYPTION_KEY_SECRET`; no separate Pi key or cryptographic algorithm
  is introduced. Context metadata rejects misplaced tenant/run records but is not
  authenticated encryption. Existing EE AES-CBC does not guarantee integrity
  against malicious storage writers. Ordinary chat inputs, checkpoints, and replay packets
  are not covered by this encryption.
- [Helm](../deployment/helm/charts/onyx/templates/agent.yaml) gives workers a separate
  service account without an automatic Kubernetes API token mount. Workers run
  without root, privilege escalation, writable root filesystems, or Linux capabilities.
  [Compose](../deployment/docker_compose/docker-compose.template.yml) applies matching
  restrictions. Workers no longer receive state Redis credentials. The local
  development launcher passes only worker settings to Bun.

## Remaining boundaries

The worker requires HTTPS unless the operator explicitly permits HTTP for local
development or separately protected transport. This check does not provision TLS.
The shared bearer token grants broad worker authority; per-run capabilities are
not implemented. Public proxies mark requests, and the agent API rejects those
requests even with a valid service token. Custom proxies must apply the same rule.
Direct API ports must remain private. API and worker pods receive the callback
token; Celery producers do not. See the [deployment contract](README.md#worker-trust-boundary).

Bundled job Redis has neither authentication nor TLS. Jobs contain identifiers,
not model credentials, but queue access still permits operational interference.
Restrict queue access with network policy and authenticated Redis where needed.
Use `rediss://` for protected Redis transport. Removing state Redis settings from
workers does not itself prevent network access to that service.

Custom provider URLs remain an egress boundary. Deployment controls must restrict
access to metadata services, internal services, and unauthorized destinations.
These changes do not add a complete provider URL policy or network isolation.

A compromised worker can read other active runs in its process. Stronger isolation
requires separate execution boundaries and narrower service credentials.
Heap dumps, diagnostics, process inspection, and privileged cluster access remain
sensitive. Other LiteLLM paths, including tool-internal inference and deep research,
are unchanged and require their own review.

## Validation and rollout

Direct validation passed for default Helm security settings, explicit service-account
and identity configuration, rejected incomplete account configuration, and all three
generated Compose variants. A synthetic local development check confirmed that
API database and state Redis credentials do not reach the worker child process.
The published Bun image started successfully with the new container restrictions;
a filesystem write attempt failed with `EROFS`.

Regression coverage is in [Google auth tests](tests/google-auth.test.ts),
[provider auth tests](tests/provider-auth.test.ts),
[Redis storage tests](../backend/tests/external_dependency_unit/chat/test_pi_storage.py),
[credential separation tests](../backend/tests/external_dependency_unit/chat/test_pi_input_storage.py),
and [host authorization tests](../backend/tests/unit/onyx/chat/test_pi_security.py).
These cover credential configurations, concurrent authorization, ambient fallback,
edition-aware cache encoding, misplaced records, and host authorization.
The initial security pass passed 26 worker tests and 562 Python chat tests.
Cache regression tests exercise both editions against Redis and PostgreSQL.
TypeScript, Python type checks, and changed-file pre-commit checks passed.
A freshly built worker image also passed readiness and in-memory authentication
checks with its root filesystem mounted read-only.

Drain queued and active Pi runs before deploying the new snapshot format.
Old input records are intentionally rejected. Deploy matching API and worker
versions and verify chat before restoring admission. EE encryption-key rotation
also requires draining pending runs; credential encryption does not use the service
token. Remove legacy credential artifacts through controlled cleanup without
exposing their contents.

This investigation found no evidence of an actual compromise. It was not a
complete forensic investigation and cannot establish that no compromise occurred.
