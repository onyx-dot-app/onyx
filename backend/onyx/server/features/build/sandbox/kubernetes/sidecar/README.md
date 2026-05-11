# Craft Sandbox Sidecar

HTTP server that runs as a sidecar container in every Craft sandbox pod. Replaces
`kubectl exec`-based file I/O and command execution with an in-pod HTTP API the
backend reaches via Service DNS.

## Why this exists

The legacy Craft sandbox manager tunnels every file read, write, listing, and
command invocation through `kubectl exec` over a WebSocket SPDY stream to the
kube-apiserver. That terminates at the cluster's control plane, adds ~150–300ms
RTT per call, requires the api-server to hold the powerful `pods/exec` permission,
and inflates audit-log volume. Putting an HTTP server in the pod eliminates all
of those problems: the api-server's SA only needs `jobs` CRUD, latency drops to
local cluster networking, and the operations are auditable as ordinary HTTP traffic.

## Endpoints

| Method | Path             | Auth   | Purpose                                              |
|--------|------------------|--------|------------------------------------------------------|
| GET    | `/healthz`       | none   | Liveness probe.                                      |
| GET    | `/readyz`        | none   | Readiness probe + idle-tracker status.               |
| GET    | `/files/read`    | bearer | Read a file from the workspace (base64-encoded).     |
| POST   | `/files/write`   | bearer | Write a file to the workspace.                       |
| GET    | `/files/list`    | bearer | List a directory.                                    |
| POST   | `/exec`          | bearer | Run an arbitrary command (control-plane trust).      |
| POST   | `/snapshot`      | bearer | Trigger a snapshot. **PR 2: stub; real impl in PR 5.** |

## Configuration (env vars, prefix `SIDECAR_`)

| Var | Default | Purpose |
|---|---|---|
| `SIDECAR_HOST` | `0.0.0.0` | Bind interface. |
| `SIDECAR_PORT` | `8080` | Bind port. |
| `SIDECAR_WORKSPACE_ROOT` | `/workspace` | Root for all file-path resolution. |
| `SIDECAR_AUTH_TOKEN` | — | Bearer token (use file form in production). |
| `SIDECAR_AUTH_TOKEN_FILE` | — | Path to a file holding the token (mount from a K8s Secret). |
| `SIDECAR_IDLE_TIMEOUT_SECONDS` | `3600` | Process exits after this many seconds without an authenticated request. |
| `SIDECAR_IDLE_CHECK_INTERVAL_SECONDS` | `30` | How often the background task evaluates the idle timer. |
| `SIDECAR_MAX_READ_BYTES` | `104857600` | 100 MiB. |
| `SIDECAR_MAX_WRITE_BYTES` | `104857600` | 100 MiB. |
| `SIDECAR_EXEC_DEFAULT_TIMEOUT_SECONDS` | `30` | Default per-exec timeout. |
| `SIDECAR_EXEC_MAX_TIMEOUT_SECONDS` | `300` | Hard ceiling on per-exec timeout. |
| `SIDECAR_LOG_LEVEL` | `INFO` | uvicorn / app log level. |

`SIDECAR_AUTH_TOKEN` or `SIDECAR_AUTH_TOKEN_FILE` is required — the sidecar refuses
to start without one rather than silently disabling auth.

## Lifecycle

Idle detection is in-process: every authenticated request bumps a
`last_interaction` monotonic timestamp. A background task polls every
`IDLE_CHECK_INTERVAL_SECONDS`, and once `IDLE_TIMEOUT_SECONDS` has elapsed it
raises `SIGTERM` against the pid. FastAPI's lifespan-shutdown path then runs the
shutdown routine (PR 5: snapshot to S3) before the process exits.

The kubelet's eviction path also lands on `SIGTERM`. The `terminationGracePeriodSeconds`
on the Job spec (set in PR 3) gives the shutdown routine room to finish.

## Local development

```sh
uv sync
SIDECAR_AUTH_TOKEN=dev-token SIDECAR_WORKSPACE_ROOT=/tmp/sandbox-ws uv run sandbox-sidecar
```

Tests:

```sh
uv run pytest
```

## Image

Built by `.github/workflows/sidecar-deployment.yml` and published to
`onyxdotapp/sandbox-sidecar:vX.Y.Z`. PR 3 wires it as a sidecar container in the
sandbox Job template.
