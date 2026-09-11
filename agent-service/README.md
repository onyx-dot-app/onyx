# Onyx agent workers

Pi owns core chat inference, tool validation, tool scheduling, and continuation.
An asynchronous worker runs many conversations concurrently; replicas share a BullMQ
queue. Pi mode has no pod per conversation or LiteLLM inference fallback. Existing tool-internal model calls and deep research retain their
current implementation.

## Engine selection

`ONYX_CHAT_ENGINE=pi` selects queued Pi execution (the default).
`ONYX_CHAT_ENGINE=legacy` selects the original in-process LiteLLM loop.
Set the same value on API and background services. Invalid values fail startup.
Legacy mode does not start Pi recovery, expose worker callbacks, or require its Redis queue or service token.
Deep research keeps its existing execution path in either mode.

Drain active chats before switching engines, then restart API and background services.
The selector applies to new turns; it does not migrate active execution or replay buffers.
There is no automatic fallback after a Pi failure, which could repeat tool effects.

For Helm, set `chatEngine: legacy`. The chart omits Pi workers, queue Redis, and related secrets.
For Docker Compose, use the legacy overlay:

```sh
docker compose -f docker-compose.yml -f docker-compose.legacy-chat.yml up -d
```

The overlay sets the engine on API and background services and disables Pi services.
With an existing Pi stack, stop `agent_service` and `agent_redis` after its runs drain.

## Ownership and transport

1. The Onyx API authenticates the user, captures bounded run inputs, and commits a
   Postgres run record. The queued record is the durable dispatch intent.
2. The official Python BullMQ producer submits `{runId, tenantId}` to `onyx-agent`.
   Queue jobs contain no conversation content, model credentials, or tool arguments.
3. A worker generates an attempt ID and claims the run through the internal API.
   Only the first durable claim receives its model configuration. Redelivery of an
   already claimed run cannot restart inference or replay tools.
4. Pi requests context and executes validated tools through short HTTP callbacks.
   Python owns authorization, retrieval, citations, application tool effects, and
   conversation persistence. Tool execution stays in the API servers.
5. Each model response uploads bounded NDJSON frames through one HTTP request.
   The API projects frames into browser packets without rebuilding the full chat
   context for each frame. The worker awaits the final checkpoint acknowledgement
   before invoking the next tool or context callback.
6. The API persists completion. Browser streams and reconnect replay read shared,
   bounded transient state; browser disconnection does not cancel the worker.

The internal API authenticates the service token and binds requests to tenant, run,
and attempt. Callbacks and model uploads carry a monotonically increasing operation
sequence. An operation is never automatically retransmitted. An active model upload
uses one API connection; callbacks can subsequently reach any API replica.

Dispatch recovery can retry a failed **delivery** while its durable run is still
queued, including a transient API failure before claim. Retained BullMQ jobs are
explicitly reprocessed rather than silently deduplicated by job ID. Every delivery
must still acquire the durable claim: retrying delivery never authorizes replay of
an already claimed agent or its tools.

`prepare` supplies context and applies prompt hooks, including reminders selected
from previous tool results. `turn_end` records all tool results, including Pi
validation failures. Nested tool implementations do not need their own queue jobs.

## Internal protocol

The API root defaults to `http://127.0.0.1:8080/internal/agent`; deployments with an
API prefix must include it in `ONYX_AGENT_API_URL`. All requests carry
`Authorization: Bearer ...` and `X-Onyx-Tenant-Id`.

| Endpoint under `/runs/{runId}` | Request                                                                                   | Response                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `claim`                        | `{attemptId}`                                                                             | `{start: ...}` or a non-claim status             |
| `callback`                     | `{attemptId, sequence, type, payload}`                                                    | `{value: ...}`                                   |
| `events-stream`                | NDJSON `{events: [...]}`; attempt and sequence in `X-Onyx-Attempt-Id` / `X-Onyx-Sequence` | JSON acknowledgement after upload and checkpoint |
| `events`                       | `{attemptId, sequence, events: [...]}`                                                    | JSON acknowledgement; used for final `done`      |
| `heartbeat`                    | `{attemptId}`                                                                             | `{cancelled: boolean}`                           |
| `finish`                       | `{attemptId, status, error?}`                                                             | JSON acknowledgement                             |

Model uploads close on `model_end`, before callbacks, or on explicit flush. A slow
API cannot accumulate unlimited model output: each upload has a 1 MiB pending
budget and a 64 KiB readable-stream queue. Frames are split into 32 KiB network
chunks. Cancellation aborts inference and pending HTTP work. An already executing
Python tool may finish its operation; cancellation cannot undo external effects.

Workers renew leases every two seconds through `POST /heartbeats` under the API
root. Each request is tenant-scoped and carries `{runs: [{runId, attemptId}]}`
(maximum 512); the response lists `{cancelled: [runId]}`. One non-overlapping
scheduler batches active leases per worker, including during drain.

## Scaling and shutdown

A worker claims at most `ONYX_AGENT_MAX_CONCURRENT_RUNS` jobs at once (default 64).
This is a concurrency bound, not a measured capacity guarantee. Runs waiting on
models or tools still occupy a slot. Provider quotas and API tool capacity require
separate limits; adding workers does not increase either.

Kubernetes deployments can use the chart's KEDA autoscaler. Its primary signal is
active plus runnable queued jobs, including prioritized jobs and excluding delayed
jobs. Every worker reports the same global queue count: aggregate
`onyx_agent_outstanding_runs` with **max**, never sum. Set the target below measured
safe per-worker concurrency, retain warm replicas, and use slow scale-down.

Docker Compose uses the same queue and image with manual replicas:

```sh
docker compose up -d --scale agent_service=4
```

Compose replicas share the host's CPU and memory. Compose does not supply a
workload-driven autoscaler or multi-host scheduler.

On SIGTERM/SIGINT the worker stops claiming new jobs, becomes unready, and keeps
renewing active queue locks and run heartbeats while draining. At the drain deadline
it aborts unfinished runs and requests an `interrupted` finalization. The process
allows another 20 seconds for cleanup before exiting forcibly. Kubernetes
`terminationGracePeriodSeconds` and Compose `stop_grace_period` must exceed this
combined window. Worker crashes and API stream failures interrupt runs; queue
redelivery is not durable agent continuation and never authorizes tool replay.

## Configuration

| Variable                           | Default                                | Purpose                                                        |
| ---------------------------------- | -------------------------------------- | -------------------------------------------------------------- |
| `ONYX_AGENT_REDIS_URL`             | `redis://127.0.0.1:6381/0`             | Persistent BullMQ queue Redis; supports `rediss://`            |
| `ONYX_AGENT_API_URL`               | `http://127.0.0.1:8080/internal/agent` | Internal Python API root                                       |
| `ONYX_AGENT_SERVICE_TOKEN`         | none                                   | Random secret of at least 32 characters; API and worker only |
| `ONYX_AGENT_ALLOW_INSECURE_HTTP` | `false` | Explicit exception for local development or separately protected transport |
| `ONYX_AGENT_SERVICE_HOST`          | `127.0.0.1`                            | Health/metrics HTTP bind address                               |
| `ONYX_AGENT_SERVICE_PORT`          | `8091`                                 | Health/metrics HTTP port                                       |
| `ONYX_AGENT_MAX_CONCURRENT_RUNS`   | `64`                                   | Per-process execution slots                                    |
| `ONYX_AGENT_RUN_TIMEOUT_SECONDS`   | `1800`                                 | Run budget including queue wait; 1–1800 seconds                |
| `ONYX_AGENT_DRAIN_TIMEOUT_SECONDS` | `1800`                                 | Graceful shutdown budget before interrupting runs              |
| `ONYX_AGENT_EVENT_BATCH_MS`        | `200`                                  | Upload frame latency bound, configurable up to 1000 ms         |

Use persistent, `noeviction` Redis for the queue. Transient replay/context state has
its own bounded storage and retention policy in the Python service. Do not rely on
separate Redis database numbers for memory isolation. Production should provision
independent queue and transient-state memory budgets.

Run snapshots separate ordinary chat inputs from connection credentials. Chat
inputs retain their existing JSON serialization and compression. API keys,
credential-bearing provider settings/options, and tool/MCP headers use Onyx's
shared cache codec and edition-aware encryption functions. Provider extension
maps stay together because their credential keys are not fixed. Only the
credential blob needs binary-to-JSON encoding; both parts share one Redis record
for atomic admission, expiration, and cleanup. **CE does not encrypt.** EE encrypts when
`ENCRYPTION_KEY_SECRET` is configured, using Onyx's existing key management.
No key derives from the service token, and no credential file is created.
Tenant, purpose, and key metadata reject misplaced credential blobs. The existing EE
AES-CBC format does not provide authenticated encryption.
Drain queued and active runs before deploying the new snapshot format or
rotating the EE encryption key. Old input records are rejected. Chat output and
tool-result snapshots retain their existing storage policy and can contain
sensitive content.

`GET /health` checks process liveness; `/ready` also checks worker readiness and
Redis connectivity. `/metrics` exposes global outstanding jobs, local active runs,
configured capacity, and drain state. Redis failures return HTTP 503 for metrics,
not a misleading zero backlog. These operational endpoints contain no chat data
and belong on the internal service network.

Provider credentials are scoped to each run. Pi supplies native provider adapters;
Claude on Vertex uses the official Anthropic Vertex client with Pi's stream parser.
Gemini and Claude on Vertex use in-memory authentication. Supplied Google JSON
credentials must contain service-account key material; external-account, local-file,
and executable credential configurations are not accepted. Missing credentials do
not enable ambient authentication. Workload identity requires host authorization
in single-tenant mode and explicit deployment opt-in. Provider requests have a
two-minute timeout and at most two retries; this does not retry the agent run or
tool execution.

The pinned Pi patch adds Google client injection and makes a supplied provider
environment authoritative. Keep the patch and security tests when updating Pi.
See [SECURITY.md](SECURITY.md) for the audit and remaining trust boundaries.

## Worker deployment security

Workers use a dedicated Kubernetes service account, without Kubernetes API token mounts.
They run as UID/GID 1000, with a read-only root filesystem and all capabilities dropped.
Compose applies the same filesystem and privilege restrictions.
No worker receives the API's transient-state Redis credentials.

`agent.allowWorkloadIdentity` defaults to `false` in Helm.
Explicitly approved deployments can enable it and configure `agent.serviceAccount.annotations`
for a dedicated, least-privileged cloud identity. Never reuse the API's cloud role.
Compose exposes the equivalent `ONYX_AGENT_ALLOW_WORKLOAD_IDENTITY` setting.
An enabled worker identity is shared by its runs; it is not tenant isolation.

The worker still holds a shared internal API service token and queue access.
A compromised worker process can cross tenant boundaries; concurrency does not provide a sandbox.
The worker requires HTTPS by default. Bundled queue Redis has no authentication or TLS.
Keep these endpoints on trusted, restricted networks. Configure HTTPS and authenticated
`rediss://` endpoints when the network trust boundary requires transport protection.

## Development and validation

For the initial migration, drain existing chats, apply the database migrations,
and deploy matching API and worker images before reopening chat traffic. Older
API replicas do not implement the worker callback protocol and cannot share its
callback service during the cutover. Provision the queue Redis and matching
service token on both services before starting workers. Subsequent deployments
use worker draining; forced shutdown interrupts unfinished turns without replay.

```sh
bun install --frozen-lockfile
bun run dev
bun run check
bun test
```

The local process-compose stack supplies the queue, API endpoint, and shared token.
The default tests exercise provider protocols, credential isolation, tool validation,
turn limits, streaming upload ordering, API failures, and upload backpressure.

Queue integration tests require an isolated Redis and the repository Python virtual
environment with the pinned `bullmq` package:

```sh
ONYX_AGENT_TEST_REDIS_URL=redis://127.0.0.1:6381/15 bun test
```

Tests use uniquely named queues and remove only those queues. They verify Python
producer/TypeScript worker interoperability, concurrent runs, duplicate delivery,
heartbeat cancellation, graceful drain, and deadline interruption. Override
`ONYX_AGENT_TEST_PYTHON` if the Python executable is not `../.venv/bin/python`.

These tests establish behavior, not a several-thousand-run capacity result. Load
tests must include realistic context sizes, model token rates, tool latency, slow
browser readers, API failures, and worker termination. Streaming uploads remove
per-frame HTTP request overhead, but projection, Redis publication, checkpoints,
and heartbeats still consume shared API and database capacity.


## Worker trust boundary

Workers are trusted backend services, like the shared API processes on main.
One deployment token authenticates the worker service; it is not a tenant or
per-worker identity. The API checks tenant routing, active attempt, expiry,
cancellation, and callback sequence before execution. Stored inputs must match
the run session; Onyx loads the user and checks session ownership when building
tools. Tool callbacks must reference unique recorded calls with matching names
and currently available tools. Pi's schema-normalized arguments remain supported.

Public nginx/Ingress and development Next.js proxies overwrite
`X-Onyx-Public-Request`. The agent API rejects marked requests with 404 even when
they carry a valid service token. Custom proxies must set this header or block
the agent routes themselves. Do not expose the API service port directly to
untrusted networks. Worker requests go directly to the private API endpoint.

Set `agent.apiUrl` (Helm) or `ONYX_AGENT_API_URL` (Compose) to a private HTTPS
endpoint with a valid certificate. Existing proxy or mesh transport can be reused;
public API ingress deliberately rejects worker callbacks. The TLS termination
hop must also have a protected path to the API. Mount a trusted CA bundle through
the existing worker volume settings when required; do not disable certificate
verification. No new certificate service or TLS proxy is included.

For local development, use `ONYX_AGENT_ALLOW_INSECURE_HTTP=true`. Helm requires
`agent.allowInsecureHttp=true` for an HTTP exception. Development Compose opts in;
production variants do not. An HTTP exception does not encrypt traffic. Only use
it for local development or when the transport is protected independently.
Generate a deployment token with `openssl rand -hex 32` and configure the same
value on the API and workers. Compose no longer supplies a known default token;
Helm generates a release-specific Secret or uses `agent.existingSecret`.

Before upgrading an existing Pi deployment, configure transport and replace any
short development token on both services. Drain active runs before rotating the
shared token. Deploy public-proxy changes together with the API changes. Celery
queue producers no longer receive the callback token. None of these controls
provide isolation between runs after complete worker-process compromise.
