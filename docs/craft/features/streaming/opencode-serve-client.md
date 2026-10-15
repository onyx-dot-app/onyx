# OpencodeServeClient design note

This document is historical. It records the design that moved Craft from the
old per-message `opencode acp` process to long-lived `opencode serve`.

The active runtime is Firecracker-only. `SandboxManager.send_message` calls
`_send_message_via_serve` in
`backend/onyx/server/features/build/sandbox/serve_transport.py`, which builds
`OpencodeServeClient` from
`backend/onyx/server/features/build/sandbox/opencode/serve_client.py`. The
sandbox itself is managed by `SandboxRuntime` and `ExecClient`; see
[Firecracker infrastructure](../../infra/firecracker.md).

## Current contract

`OpencodeServeClient` is the Python HTTP client for one in-pod OpenCode server.
The server listens on `OPENCODE_SERVE_PORT`, currently `4096`, inside the main
sandbox container.

The client owns:

- OpenCode health checks
- OpenCode session lookup and creation
- prompt submission through `prompt_async`
- event subscription through the pod event bus
- event translation into Onyx sandbox events
- abort requests when a turn is cancelled or times out

The caller-facing event type is `SandboxEvent`, imported from
`backend/onyx/server/features/build/sandbox/event_schema.py`. That wrapper
still re-exports the upstream `agent-client-protocol` models. Keep imports
behind the wrapper so a future inline can be one file.

## Boundaries

The client does not know how the pod was created. It receives a base URL,
password, event bus, and timeout values from the sandbox manager layer.

The client does not do filesystem work. File operations, snapshots, managed
content pushes, and OpenCode history moves go through the immutable guest
helper under `image/guest/`.

The client does not surface OpenCode permission prompts to the frontend.
OpenCode permission asks are handled internally according to the current
transport code. External app approvals use the sandbox egress proxy, not
OpenCode's permission API.

## Deferred schema cleanup

The old design planned a later phase to inline schema models and remove
`agent-client-protocol`. That is still deferred.

If that work resumes:

1. Replace the re-exports in `sandbox/event_schema.py` with local Pydantic
   models.
2. Keep `model_dump(by_alias=True)` output byte-compatible for persisted tool
   events.
3. Remove the dependency from `pyproject.toml` and re-lock.
4. Grep Enterprise Edition for direct `acp.schema` imports before merging.

Do not rename the event classes as part of that change. It would touch every
consumer without changing the wire contract.
