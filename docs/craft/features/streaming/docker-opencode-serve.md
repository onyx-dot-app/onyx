# Docker sandbox → opencode-serve

Port `DockerSandboxManager` from the per-message `opencode acp` exec to the long-lived `opencode serve` HTTP transport that the Kubernetes backend already uses. Prerequisite for [`drop-acp-layer.md`](./drop-acp-layer.md), which deletes the ACP transport entirely.

## Issues to Address

`DockerSandboxManager.send_message` (`backend/onyx/server/features/build/sandbox/docker/docker_sandbox_manager.py:1039-1103`) spawns a `DockerACPExecClient` per user message — same per-process startup cost, same session-lifetime-tied-to-one-turn, same opencode-1.15.7-drops-the-terminator bug enumerated in [`opencode-serve-migration.md`](./opencode-serve-migration.md) §Issues. The Kubernetes backend already migrated; self-hosted docker-compose deployments are stuck on the buggy path.

The blockers, all docker-specific:

1. **No serve client wiring on the Docker manager.** `send_message` takes `opencode_session_id` / `agent_provider` / `agent_model` kwargs but marks them `noqa: ARG002 — serve-only` and ignores them. There is no `_send_message_via_serve`, no `ensure_opencode_session` override, no `prompt_slot` impl, no event bus.
2. **No password provisioning.** The K8s manager creates a per-pod `V1Secret` holding `OPENCODE_SERVER_PASSWORD` + `OPENCODE_CONFIG_CONTENT` (`kubernetes_sandbox_manager.py:372-429`). Docker has no equivalent — `build_container_create_kwargs` (`docker_sandbox_manager.py:347-350`) is an env allowlist of `{ONYX_PAT, ONYX_SERVER_URL}` enforced by `test_docker_manager_config.py`.
3. **No `OPENCODE_CONFIG_CONTENT` at provision time.** The K8s path uses pod-wide `build_multi_provider_opencode_config` so per-prompt model overrides can switch providers without restarting opencode (`opencode_config.py:1-7` — opencode-serve does not hot-reload config). The Docker path writes per-session `opencode.json` files via `build_opencode_config` in `setup_session_workspace` (`docker_sandbox_manager.py:668`) and `_regenerate_session_config` (`:1005-1033`, write at `:1018-1028`), which serve cannot pick up since it loaded its provider list at startup.
4. **The image's entrypoint already runs `opencode serve`**, but only when `AGENT_TRANSPORT=serve` (`backend/onyx/server/features/build/sandbox/image/entrypoint.sh:36` sets `TRANSPORT="${AGENT_TRANSPORT:-acp}"`, gate at `:46` (`[ "$TRANSPORT" != "serve" ]` → idle), serve branch at `:56-80`). The Docker manager today never sets `AGENT_TRANSPORT`, so the entrypoint falls through to the `tail -f /dev/null` idle branch and `opencode acp` is exec'd per message.
5. **Network reachability.** K8s reaches opencode-serve via the per-pod `ClusterIP` Service at `service_name.namespace.svc.cluster.local:4096` (`kubernetes_sandbox_manager.py:2183-2194`). Docker would need to reach the sandbox container over the `onyx_craft_sandbox` bridge, by container name on port 4096. No host port mapping (would break isolation); api_server must be on the same bridge or have a route into it.

## Important Notes

### Why this is a separable PR from `drop-acp-layer.md`

Two distinct kinds of risk:

- This PR adds a new code path to a previously single-path manager and verifies it works against a real `opencode serve` running in a Docker container. The blast radius is self-hosted users.
- `drop-acp-layer.md` deletes code that has already soaked. The blast radius is "did we miss a branch."

Bundling them turns the deletion PR into a feature PR with a deletion riding along. Reviewer can't tell whether a failing test is "Docker serve has a bug" or "we missed an ACP branch." Keep them separate even if they land back-to-back.

### Reuse vs. duplicate the K8s serve plumbing

The K8s manager owns six pieces of serve plumbing that map cleanly to Docker:

| K8s | Docker equivalent | Reuse strategy |
|---|---|---|
| `_get_service_name` → DNS name | container name on bridge | Different impl, same interface — keep on each manager |
| `_get_opencode_secret_name` + `_provision_opencode_secret` (V1Secret) | per-container env var injected at create | Different impl, same interface — but factor the password generation (`secrets.token_urlsafe(32)`) and the cleartext value into a small helper if it's used in both |
| `_read_opencode_password` | dict lookup from container env (read back via Docker inspect) | Different impl |
| `_serve_base_url` | `f"http://{container_name}:{OPENCODE_SERVE_PORT}"` | Trivial |
| `_wait_for_opencode_serve_ready` | identical logic against the new base_url | **Move to base.py** as a default impl taking `base_url` + `password`; both managers call it |
| `_get_or_create_event_bus` + `_build_serve_client` + `_event_buses` cache | identical logic | **Move to base.py** as a mixin or default impl; the only manager-specific bit is `_serve_base_url` |

The push daemon (`PUSH_DAEMON_PORT=8731`) is already reached via container name on the Docker bridge from the api_server (see `DockerSandboxManager._docker` and `docker_sandbox_manager.py:32-46` docstring). Serve reachability is the same pattern; no new networking design is needed.

### Provisioning order and the env-allowlist invariant

`test_docker_manager_config.py` locks down `build_container_create_kwargs` to a fixed env allowlist. Adding `OPENCODE_SERVER_PASSWORD`, `OPENCODE_CONFIG_CONTENT`, `OPENCODE_SERVE_PORT`, and `AGENT_TRANSPORT=serve` (transitional — see §Provisioning) means updating both the function and its test in the same change. Keep the invariant ("no S3/MinIO/Postgres/Redis creds, no compose service hostnames") and add only the four serve-related vars.

Password generation happens during `provision()`, *before* `build_container_create_kwargs` is called, and the cleartext is passed through as a parameter. Do not store it on disk on the api_server — the only persistent store is the Docker container's env, which `_read_opencode_password` recovers via `client.containers.get(name).attrs["Config"]["Env"]`.

### One-config-per-container (not one per session)

Because opencode-serve loads providers at startup, the Docker manager must:

- Drop the per-session `opencode.json` writing in `setup_session_workspace` and `_regenerate_session_config` (mirrors K8s, which already deletes this branch when `AGENT_TRANSPORT=serve` — `kubernetes_sandbox_manager.py:1459-1471`).
- Build a single `build_multi_provider_opencode_config` at provision time and inject it as `OPENCODE_CONFIG_CONTENT`.
- Accept that per-prompt provider switching now goes through the prompt-body model override that `OpencodeServeClient.send_message` already passes (see `_send_message_via_serve` in K8s).

The per-session `opencode.json` files become dead but harmless. Leave them out rather than writing them — serve never reads them and they pollute snapshots.

### LLM provider list at provision time

K8s pulls `LLMProviderConfig` for every configured provider from the DB at provision (`kubernetes_sandbox_manager.py:1166-1174`). Docker's `provision()` (`docker_sandbox_manager.py:499-530`) takes a single `LLMProviderConfig`. To call `build_multi_provider_opencode_config`, the signature has to accept a list. Either:

- Change `provision()` to take `llm_configs: list[LLMProviderConfig]` and have the session manager pass all configured providers (consistent with K8s), or
- Keep the single-provider signature and call `build_opencode_config` to build a single-provider `OPENCODE_CONFIG_CONTENT` — same behavior as today's per-session file, but injected at startup instead.

Pick the second for this PR — it minimizes the surface area of the change. The first is a follow-up if/when Docker users actually need cross-provider per-prompt switching.

### Docker snapshots do not preserve opencode history today

Normal workspace snapshots capture per-session `outputs/` and `attachments/`
only. They do not include opencode's sandbox-global data directory. The
Kubernetes backend persists that history through separate sidecar
`/opencode-history/*` endpoints, but Docker does not currently have an
equivalent opencode-history persistence path.

If Docker moves to `opencode serve`, preserve session history with a separate
sandbox-level archive instead of putting opencode data into normal per-session
workspace snapshots. The SQLite backup detail matters there: a live
`opencode serve` process can have WAL state, so the archive should be created
from a coherent SQLite backup rather than a raw mid-write file copy.

### Networking from api_server to sandbox container

The api_server container needs to be on the `onyx_craft_sandbox` bridge network to resolve `sandbox-{id}` by name on port 4096. This is already true for the push-daemon path (`PUSH_DAEMON_PORT=8731` on the same bridge); no compose change. Verify by reading the compose file and the existing push-daemon code path before claiming "no change" in the PR description.

## Implementation Strategy

### Factor shared serve plumbing to `base.py`

Today `SandboxManager` (`backend/onyx/server/features/build/sandbox/base.py`) already defines `prompt_slot`, `ensure_opencode_session`, `list_subagents`, and `subscribe_to_opencode_session` as abstract / no-op defaults. K8s overrides all four with the serve-only real implementations, each gated on `AGENT_TRANSPORT == AgentTransport.SERVE`. The other serve helpers (`_wait_for_opencode_serve_ready`, `_get_or_create_event_bus`, `_build_serve_client`, `_send_message_via_serve`, `_event_buses`/`_event_buses_lock`/`_terminated_sandboxes` state) live only on the K8s subclass.

Move these to base:

- `_wait_for_opencode_serve_ready` — promote to a concrete base method that calls two new abstracts: `_serve_base_url(sandbox_id) -> str` and `_read_opencode_password(sandbox_id) -> str | None`.
- `_get_or_create_event_bus` + the `_event_buses` cache + `_event_buses_lock` + `_terminated_sandboxes` set.
- `_build_serve_client`.
- `_send_message_via_serve` — the whole body; it's already manager-agnostic once `_serve_base_url` and `_read_opencode_password` are abstract.
- Replace the four base-class stubs (`prompt_slot`, `ensure_opencode_session`, `list_subagents`, `subscribe_to_opencode_session`) with the real K8s implementations, and delete the K8s overrides.

Subclasses implement only `_serve_base_url` and `_read_opencode_password`.

Doing this *before* writing the Docker serve path means the new path is ~50 lines, not ~500.

### Parameter naming mismatch at the serve-client boundary

`OpencodeServeClient.send_message` takes `model_provider` / `model_id`, but `KubernetesSandboxManager.send_message` (and the manager interface generally) takes `agent_provider` / `agent_model`. The K8s `_send_message_via_serve` does the rename at the call site. When the body moves to base.py, the rename moves with it — Docker's `send_message` keeps the manager-side names. Don't introduce a third naming convention.

### Wire `DockerSandboxManager` to the new base

1. **Password lifecycle.** In `provision()`, generate `secrets.token_urlsafe(32)`, build the `OPENCODE_CONFIG_CONTENT` JSON (single-provider via `build_opencode_config`), pass both into `build_container_create_kwargs`.

2. **Env allowlist.** Extend `build_container_create_kwargs` to take `opencode_password: str` and `opencode_config_json: str`, add them to the env dict alongside `OPENCODE_SERVE_PORT=4096` and `AGENT_TRANSPORT=serve`. Update `test_docker_manager_config.py` to assert the new allowlist (still no S3/MinIO/Postgres/Redis creds, still no compose hostnames).

3. **`_serve_base_url`.** Return `f"http://{_sandbox_container_name(sandbox_id)}:{OPENCODE_SERVE_PORT}"`.

4. **`_read_opencode_password`.** Read the container's env via `self._docker.containers.get(name).attrs["Config"]["Env"]`, parse the `OPENCODE_SERVER_PASSWORD=...` line.

5. **`send_message`.** Replace the entire body (minus packet logging) with a call to the new base-class `_send_message_via_serve` (which lives on base after the refactor) — or, if that turns out to be too invasive to factor, copy the K8s `_send_message_via_serve` body verbatim and minimize from there.

6. **`ensure_opencode_session` override.** Same as K8s — build a serve client, call `client.ensure_session(None, cwd=session_path, title=...)`. Or just inherit the base-class impl after the refactor.

7. **Session setup.** In `setup_session_workspace` (`docker_sandbox_manager.py:682-744`), drop the `printf '%s' '{opencode_json}' > {session_path}/opencode.json` line (around `:668`). Same for `_regenerate_session_config` (`:1005-1033`, write at `:1018-1028`), which is called from `restore_snapshot` (`:920`). AGENTS.md stays.

8. **Cleanup on terminate.** When `terminate()` removes the container, the event bus + the cached opencode password go with it. The base-class `_terminated_sandboxes` machinery handles this generically; verify it fires for Docker by hooking it into `terminate()`.

### Image considerations

No image change required — the existing image already runs `opencode serve` when `AGENT_TRANSPORT=serve`. Once this PR lands and Docker injects `AGENT_TRANSPORT=serve` at container create, the entrypoint takes the serve branch.

The `AGENT_TRANSPORT=serve` env var is transitional. It goes away in [`drop-acp-layer.md`](./drop-acp-layer.md), at which point the entrypoint becomes unconditional.

### Documentation

Update `docs/craft/opencode-serve-migration.md` §"Migration phases" to note Docker is now serve-by-default. Add a one-paragraph entry to `docs/craft/issues/opencode-serve-deploy-gotchas.md` for the docker-compose specifics: api_server needs to be on `onyx_craft_sandbox` bridge, the password lives in container env, snapshot/restore needs the abort-before-tar guard.

## Tests

**External-dependency-unit** (`backend/tests/external_dependency_unit/craft/`):
- `test_docker_sandbox_serve_streaming.py` keeps the direct transport/event matrix against a Docker-provisioned sandbox container. The Craft k8s lane now covers deployed API/Celery turn handoff through `backend/tests/integration/tests/craft/k8s/test_messages_api_k8s.py` instead of directly calling `KubernetesSandboxManager.send_message`.
- Update `backend/tests/integration/tests/craft/k8s/test_kubernetes_sandbox_file_ops.py` if any imports churn from the base.py refactor.

**Unit** (`backend/tests/unit/onyx/server/features/build/sandbox/`):
- `test_docker_manager_config.py` — extend the env-allowlist assertion to include the four new serve env vars. Assert the OLD allowlist no longer matches (catches regressions in either direction).
- New `test_docker_provision_opencode_secret.py` — assert password generation is per-provision and that `OPENCODE_CONFIG_CONTENT` is a valid `build_opencode_config` JSON.

**Integration** (`backend/tests/integration/tests/craft/`):
- `test_messages_api.py` already covers the serve path generically; verify it runs against the Docker backend (`SANDBOX_BACKEND=docker`) in CI. If not, parametrize.

**Existing tests that must not regress:**
- `test_docker_acp_exec_client.py` — this test exercises the path being deleted by `drop-acp-layer.md`, not this PR. It must still pass here (the ACP code is still in the tree).

## Out of scope

- Multi-provider `OPENCODE_CONFIG_CONTENT` for Docker. Single-provider is sufficient and matches today's behavior; follow-up when needed.
- Deleting the Docker ACP exec client (`DockerACPExecClient`). That happens in [`drop-acp-layer.md`](./drop-acp-layer.md).
- Changing the network policy / compose file to expose port 4096 to the host. Sandbox-to-host port mapping is an explicit isolation violation; the bridge-network path is the only path.
- Cross-provider per-prompt switching on Docker. Comes for free once the multi-provider config is wired (separate PR).
