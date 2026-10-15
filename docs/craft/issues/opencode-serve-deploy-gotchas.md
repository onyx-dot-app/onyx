# Opencode-serve deploy gotchas

This is a historical rollout note from the first `opencode serve` cluster
deployment. The active sandbox runtime is now Firecracker-only; see
[Firecracker infrastructure](../infra/firecracker.md).

Use this file for failure signatures and recovery context only. For current
runtime ownership, read `SandboxManager`, `SandboxRuntime`, `ExecClient`, and
`OpencodeServeClient` in:

- `backend/onyx/server/features/build/sandbox/manager.py`
- `backend/onyx/server/features/build/sandbox/runtime.py`
- `backend/onyx/server/features/build/sandbox/exec.py`
- `backend/onyx/server/features/build/sandbox/opencode/serve_client.py`

## Failure modes from the rollout

### Sandbox namespace RBAC missed Secrets

Symptom:

```text
secrets "sandbox-<id>-opencode-auth" is forbidden
```

The API server needs sandbox-namespace access to the per-pod Secret that holds
`OPENCODE_CONFIG_CONTENT` and `OPENCODE_SERVER_PASSWORD`. Current code creates,
reads, replaces, and deletes that Secret from `SandboxRuntime`.

The chart-managed sandbox RBAC must cover those operations. `replace` maps to
the Kubernetes `update` verb, not `patch`.

### Mutable tags used a cached sandbox image

Symptom: a new sandbox pod ran an older image after a mutable tag moved.
`opencode serve` was not listening on port `4096`, or the container behaved
like the prior image.

Kubernetes defaults to `IfNotPresent` unless the deployment sets another pull
policy. Use app-aligned immutable tags for customer deployments. If an internal
environment deliberately uses `latest`, `beta`, or `edge`, set
`configMap.SANDBOX_IMAGE_PULL_POLICY=Always` and recreate affected pods.

The image prepuller shares the same image reference and pull policy as sandbox
pods. Keep them tied together.

### Secret updates did not refresh pod environment

Symptom: the Secret contained a new `OPENCODE_CONFIG_CONTENT`, but the running
sandbox process still saw the old value.

Kubernetes snapshots `secretKeyRef` environment variables at container start.
Updating the Secret does not update env vars in a running pod. Recreate the
sandbox pod when provider config must change for an already-provisioned
sandbox.

### Build-mode provider filters hid admin providers

Craft only preloads LLM providers selected by the build-mode provider query.
Historically, an admin provider named `anthropic` did not participate in Craft
until a `build-mode-anthropic` row existed with visible models.

Provider loading still depends on the build-mode provider path. Check the
current query before changing this behavior.

### Provider de-duplication is by provider type

The multi-provider OpenCode config starts with the session default provider.
Additional build-mode rows with the same provider type can be skipped. To
preload more than one provider type, each build-mode row must have a distinct
provider type and at least one visible model.

## Runtime chain to remember

1. Admin provider rows determine which build-mode providers are available.
2. `BuildSession` stores the selected provider and model.
3. `SandboxRuntime` writes the per-pod Secret with `OPENCODE_CONFIG_CONTENT`
   and `OPENCODE_SERVER_PASSWORD`.
4. The sandbox pod loads those values as env vars at container start.
5. The entrypoint starts `opencode serve` on `OPENCODE_SERVE_PORT`.
6. `OpencodeServeClient` posts prompts and reads events through the pod event
   bus.

The fixed OpenCode basic-auth username is `opencode`. The password comes from
`OPENCODE_SERVER_PASSWORD`.

## Common signatures

| Error or log line | Likely cause |
|---|---|
| `secrets ... is forbidden` | Sandbox namespace RBAC is missing Secret verbs. |
| `Connection refused` on OpenCode session calls | `opencode serve` is not ready or has crashed. |
| `ProviderModelNotFoundError` | Provider was not loaded into OpenCode config, or the running pod has stale env. |
| `opencode /event stream did not become ready` | Event bus did not subscribe before the turn deadline. |
| Pod image digest differs from the pushed digest | Mutable tag plus cached node image. |

## Follow-ups

Some items from the original rollout are already represented in current code
and tests, such as cold-pod retry and event-bus reset behavior. Do not treat
this document as proof that the full Firecracker and browser flow passes today.
Run the real flow before making that claim.
