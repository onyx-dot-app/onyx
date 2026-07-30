# Opencode-serve transport: deploy & runtime gotchas

**Audience:** future engineers (and agents) deploying or debugging the
opencode-serve transport on a real Kubernetes cluster. Captures the
failure modes hit during the first production-cluster rollout and the
institutional knowledge about how the opencode-serve provider chain
wires up at runtime.

**Status:** the rollout succeeded after the workarounds below. The
underlying defects (RBAC gap, mutable-tag image cache, env-var refresh
race) are real and should be fixed in source rather than patched per
environment.

---

## 1. Things that broke (in the order they were hit)

### 1.1 RBAC gap: `secrets` not in `api-server-role`

**Symptom:**

```
Session creation failed: (403) Forbidden
secrets "sandbox-<id>-opencode-auth" is forbidden:
User "system:serviceaccount:onyx:onyx-workload-access" cannot
get resource "secrets" in API group "" in the namespace "onyx-sandboxes"
```

**Root cause:** the api server's Role in the sandbox namespace was
authored before the opencode-serve transport landed. It only granted
verbs on `pods`, `pods/exec`, and `services`. The new transport adds a
per-pod K8s `Secret` (`sandbox-<id>-opencode-auth`) holding the
`OPENCODE_CONFIG_CONTENT` and `OPENCODE_SERVER_PASSWORD` env values; the
api server `create`/`get`/`replace`/`delete`s it during provision and
cleanup.

**Fix:** add the verbs the api server actually uses to whatever defines
the Role in your deployment system.

```yaml
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["create", "get", "update", "delete"]
```

These are exactly the four verbs the api server exercises — and no more.
Map each to the `_core_api.` call that needs it:

| call (`kubernetes_sandbox_manager.py`) | HTTP method | RBAC verb |
| -------------------------------------- | ----------- | --------- |
| `create_namespaced_secret`             | POST        | `create`  |
| `read_namespaced_secret`               | GET         | `get`     |
| `replace_namespaced_secret`            | PUT         | `update`  |
| `delete_namespaced_secret`             | DELETE      | `delete`  |

Watch out: `replace_namespaced_secret` is a **PUT**, which maps to the
`update` verb — **not** `patch`. If you grant `patch` instead of
`update`, the happy path still works but the 409-race re-provision
branch (see §1.3 — the path that calls `replace_namespaced_secret` after
a create conflict) will intermittently 403. `list`/`watch` are not used
on secrets at all.

`backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py`
is the source of truth for which k8s resources the api server touches —
grep for `_core_api.` method calls if you need to re-derive the verb set.

### 1.2 Mutable tags + cached node images

**Symptom:** after pushing a new sandbox image with a mutable tag
(`latest`, `beta`, or `edge`),
freshly-provisioned sandbox pods kept running the **old** image.
opencode-serve was not listening on `:4096`; the container appeared to
be running the prior placeholder behavior.

**Root cause:** sandbox pods are created with
`imagePullPolicy: IfNotPresent` by default. When the configured image
reference is mutable, the kubelet sees an image with that tag already
cached on the node and skips the pull.

**Fix:** for Kubernetes, use app-aligned immutable tags, or set
`SANDBOX_IMAGE_PULL_POLICY=Always` when deliberately running a moving tag.
For Docker compose, the Docker sandbox manager refreshes moving sandbox tags
once per API process because sandbox containers are created outside compose.

### 1.3 `OPENCODE_CONFIG_CONTENT` env doesn't refresh on Secret update

**Symptom:** opencode-serve kept reporting `Model not found:
anthropic/claude-opus-4-7` even after:

- adding the missing `build-mode-anthropic` admin LLM provider,
- letting the api server re-provision the Secret (verified via
  `kubectl get secret … -o jsonpath='{.data.config}' | base64 -d` to
  show both providers in the new content).

But `kubectl exec sandbox-… -- env | grep OPENCODE_CONFIG_CONTENT`
still showed the **old, single-provider** value.

**Root cause:** Kubernetes does not propagate `Secret` updates to env
vars on running pods. Env from `secretKeyRef` is a snapshot taken at
container start. Only **pod deletion** (or recreate-replace at the pod
level) forces the kubelet to read the current Secret.

**Symptom amplification:** opencode-serve reads `OPENCODE_CONFIG_CONTENT`
**directly at startup** and uses that env value as the source of truth
for its provider registry. Stale env → stale opencode provider list.
`_provision_opencode_secret` rebuilds the Secret correctly, but no code
path in the api server deletes the pod afterward.

**Recovery:** `kubectl delete pod sandbox-<id>` after any admin
LLM-provider change that needs to reach an already-provisioned sandbox.
The api server's normal reconciliation (health check fails → terminate
→ re-provision) recreates the pod, which loads fresh env from the
current Secret.

**Source-level fix (deferred):** when the api server detects that
`all_llm_configs` has changed vs. the deployed sandbox, it should
delete the pod (forcing env refresh), not just `replace_namespaced_secret`.

### 1.4 `_get_all_llm_configs` only picks up `build-mode-*` providers

**Symptom:** admin had an Anthropic provider configured with
`name: "anthropic"`. opencode prompts for `providerID: anthropic`
returned `ProviderModelNotFoundError`. The sandbox's
`OPENCODE_CONFIG_CONTENT` only contained `openai`.

**Root cause:** `fetch_all_build_mode_llm_providers` in
`backend/onyx/server/features/build/db/build_session.py` filters with
`LLMProviderModel.name.like("build-mode-%")`. Providers without the
`build-mode-` name prefix are silently dropped during sandbox
provisioning.

**Fix:** add a second `LLMProvider` row with `name = "build-mode-anthropic"`
(the `provider` type stays `anthropic`, same API key, same visible
models). Same pattern for any other provider you want preloaded.

**Why the prefix exists:** it discriminates the craft-mode LLM provider
set from the regular chat product's providers so API keys and model
visibility don't bleed across products.

### 1.5 `_get_all_llm_configs` de-dups by provider type, not by row

When the user's BuildSession has `agent_provider="anthropic"`, the
default `llm_config` IS anthropic. `_get_all_llm_configs` then does
roughly:

```python
configs = [default]
seen_providers = {default.provider}  # {"anthropic"}
for provider in fetch_all_build_mode_llm_providers(db):
    if provider.provider in seen_providers:  # build-mode-anthropic → "anthropic" → skip
        continue
    …
```

So the multi-provider list collapses back to `[anthropic_config]` if
the only other `build-mode-*` row is also anthropic. To have a sandbox
preloaded with two providers, you need two `build-mode-*` rows with
**different** `provider` types.

### 1.6 Bus self-close residue (already shipped)

`51b780b9f8` — `PodEventBus.closed` property + eviction in
`_get_or_create_event_bus`. Mentioned here so future readers
inspecting the bus lifecycle understand the existing safety net: when
a bus exhausts its reconnect budget (20 consecutive failures), it
self-closes; the next `_get_or_create_event_bus` call evicts it and
builds a fresh one with the current Secret's password.

### 1.7 Cold-pod connection errors during `ensure_session` (already shipped)

`e6e8a109e9` — 3-attempt retry with linear backoff on
`httpx.ConnectError`/`RemoteProtocolError` in
`_http_with_cold_pod_retry`. Subsequently tightened in `28fd724314` —
POST `/session` retries only on `ConnectError` (not
`RemoteProtocolError`) to avoid an orphan-session leak.

---

## 2. How the opencode provider chain actually wires up

This is the load-bearing institutional knowledge. Without it the bugs
in §1 look like a random pile of subsystems; with it they're obvious in
advance.

### 2.1 End-to-end data flow

1. **Admin UI** writes `llm_provider` rows. The `name` field controls
   whether the row participates in craft (`build-mode-*` pattern).
   `provider` is the type (`anthropic`, `openai`, `openrouter`, …).
2. **BuildSession created** → `agent_provider` / `agent_model` record
   the user's selection. Defaults come from `fetch_default_llm_model()`.
3. **Sandbox provisioning** (`KubernetesSandboxManager.provision`):
   - `_get_llm_config(requested_provider_type, requested_model_name)`
     resolves the **default** for this sandbox. Tries
     `fetch_llm_provider_by_type_for_build_mode(provider_type)` first
     (which prefers `build-mode-{type}` then falls back to any provider
     of that type). Returns an `LLMProviderConfig`.
   - `_get_all_llm_configs(default=llm_config)` builds the full list:
     `[default]` + every other `build-mode-*` provider whose `provider`
     type isn't already in `seen_providers` and that has at least one
     `is_visible=True` model.
   - `build_multi_provider_opencode_config(providers, default_provider,
     default_model, disabled_tools)` produces the opencode.json shape:
     `{$schema, model, provider: {<type>: {options.apiKey, models}},
     enabled_providers, permission}`.
   - The JSON is `json.dumps`'d and written to a per-pod K8s Secret
     (`sandbox-<id>-opencode-auth`, key `config`) alongside the per-pod
     `password` (HTTP Basic auth for opencode-serve).
4. **Pod spec** references the Secret via two `secretKeyRef` env
   entries: `OPENCODE_CONFIG_CONTENT` and `OPENCODE_SERVER_PASSWORD`.
   **k8s does NOT propagate Secret updates to running pod envs** — see
   §1.3.
5. **Entrypoint** runs `opencode serve --hostname 0.0.0.0 --port
   "$OPENCODE_SERVE_PORT" --print-logs` in a `while true` restart loop.
   It does NOT materialize `OPENCODE_CONFIG_CONTENT` to a file — the
   env var is opencode's primary config source (opencode also probes
   filesystem paths but the env path is what craft uses).
6. **opencode-serve** registers providers **lazily** on the first
   prompt. Watch the logs for the sequence:
   ```
   service=provider status=started
   service=provider providerID=<X> found
   service=provider status=completed
   ```
   A missing `found` line for a provider means opencode silently
   dropped it from the registry.
7. **Per-prompt model override:** the api server's `_post_prompt_async`
   sets `body["model"] = {"providerID": …, "modelID": …}` when both are
   set on the BuildSession. opencode looks up `providerID/modelID` in
   its merged registry; if the providerID isn't registered →
   `ProviderModelNotFoundError`.

### 2.2 Auth

- `OPENCODE_SERVER_USERNAME = "opencode"` (constant in
  `backend/onyx/server/features/build/configs.py`). **Not** `"onyx"` —
  this tripped up curl-based debugging.
- Password comes from the `OPENCODE_SERVER_PASSWORD` env (mounted from
  the per-pod Secret). Both the api server (HTTP Basic) and any
  in-pod curl debugging need this exact username.

### 2.3 Common error signatures

| Error / log line | Meaning |
|---|---|
| `secrets … is forbidden … namespace "onyx-sandboxes"` | §1.1 — api-server Role missing `secrets` verbs |
| `[Errno 111] Connection refused` on POST `/session` | opencode-serve not bound to `:4096`. Cold pod, crashloop, or process death |
| `ProviderModelNotFoundError` w/ bundled-model suggestions | Provider not registered in opencode (silent drop from env config), or config not loaded |
| `Sandbox … has status provisioning and is being created by another request` | Intentional guard. Two concurrent requests on the same user's mid-provision sandbox |
| Sandbox pod shows old behavior despite new image push | Cached mutable-tag digest on the node + `IfNotPresent` policy (§1.2) |
| `opencode /event stream did not become ready` | Bus reader failed to subscribe before the per-turn deadline. Causes: opencode-serve not bound yet (cold), or auth mismatch between bus's cached password and current Secret (bus will self-close and rebuild on next prompt — see §1.6) |
| opencode-serve restarts in tight loop, exit 143 | SIGTERM propagated from the entrypoint trap. Almost always operator-induced |

### 2.4 Diagnostic snippets

**What providers does THIS sandbox actually have loaded?**
```bash
SBX=$(kubectl -n onyx-sandboxes get pods -o name | head -1 | sed 's|pod/||')
kubectl -n onyx-sandboxes exec "$SBX" -c sandbox -- sh -c 'echo "$OPENCODE_CONFIG_CONTENT"' \
  | python3 -c 'import sys, json; d=json.load(sys.stdin); print("enabled:", d.get("enabled_providers")); print("keys:", list(d.get("provider",{}).keys()))'
```

**What does opencode-serve think it loaded?** Tail the sandbox
container logs and look for `service=provider providerID=<X> found`
lines after the first prompt. If a provider is in the env var but
missing from this log, opencode silently dropped it (usually a JSON
shape problem or missing API key).

**Test the opencode API directly** (auth user is `opencode`, NOT `onyx`):
```bash
kubectl -n onyx-sandboxes exec sandbox-<id> -c sandbox -- sh -c '
  curl -s -u "opencode:$OPENCODE_SERVER_PASSWORD" http://localhost:4096/doc \
    | python3 -m json.tool | head -20
'
```

**Tail opencode logs across pods (with `stern`):**
```bash
stern -n onyx-sandboxes sandbox -c sandbox
```

---

## 3. Recovery recipes

### Symptoms cluster A: "my admin LLM provider isn't reaching the sandbox"

1. Confirm the provider's `name` matches `build-mode-%`:
   ```sql
   SELECT id, name, provider, default_model_name FROM llm_provider;
   ```
   If not, rename (or create a duplicate `build-mode-*` row pointing at
   the same API key). The `provider` field stays as the type.
2. Confirm at least one `model_configuration` has `is_visible=true` for
   that provider — silently skipped otherwise.
3. Delete the user's sandbox pod to force env refresh from the Secret
   (§1.3). The api server's reconciliation will re-provision with the
   updated provider list.
4. Tail opencode logs for `service=provider providerID=<X> found` after
   the first prompt. If missing, the provider got dropped — recheck
   the JSON shape in `OPENCODE_CONFIG_CONTENT`.

### Symptoms cluster B: "new sandbox image isn't being used"

1. Check the pod's actual image digest:
   ```bash
   kubectl -n onyx-sandboxes get pod sandbox-<id> \
     -o jsonpath='{.status.containerStatuses[?(@.name=="sandbox")].imageID}'
   ```
2. Compare with the digest of the image you just pushed.
3. If they differ, the node has a cached older image and the pod is
   running that. For Kubernetes, deploy a matching immutable app/sandbox tag or
   set `SANDBOX_IMAGE_PULL_POLICY=Always` for a moving-tag environment, then
   recreate the affected sandbox pod.

### Symptoms cluster C: "RBAC 403 on a sandbox-namespace resource"

The api server's Role in the sandbox namespace is out of date — see
§1.1. Cross-reference current Role rules against the k8s API calls
made from `kubernetes_sandbox_manager.py` (grep for `_core_api.` /
`_rbac_api.` method names) to derive the verb set the api server
actually needs.

---

## 4. Architectural follow-ups

| Item | Why it matters | Where to land it |
|---|---|---|
| App-aligned sandbox tags | Avoids app/sandbox version skew; Kubernetes immutable tags avoid mutable-tag cache traps without adding a registry check to every sandbox pod start | release workflow + sandbox PodTemplate defaults |
| Recreate pod on Secret content change | Fixes §1.3 — env doesn't refresh on Secret update | `_provision_opencode_secret` or the provisioning caller |
| `secrets` verbs in the chart-managed sandbox-namespace Role | Stops the §1.1 403 from recurring on every fresh deploy | Onyx helm chart's sandbox-rbac template |
| Pre-seed `build-mode-*` providers in admin onboarding | Avoid the silent-skip filter trap in §1.4 | Onyx admin / setup wizard |
| Surface "sandbox provisioning" via 409 + Retry-After | Instead of `RuntimeError` → JSON dump, return a clean wait/retry signal the FE can poll on | `session/manager._stream_cli_agent_response` |
| Wait for opencode-serve `/doc` before reporting RUNNING | Closes the "k8s-ready but opencode-not-bound" window where the first prompt races a cold opencode | `KubernetesSandboxManager.provision` (landed alongside this doc) |

---

## 5. Provenance

Captured during the first production-cluster rollout of the
opencode-serve transport. The imperative recovery commands
above were validated against a single-tenant cluster; the source-level
fixes are tracked in §4.
