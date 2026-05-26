# Craft-dev deploy postmortem: `experimental-cc4a.95` and the opencode-serve provider chain

**Audience:** future agents (and humans) deploying craft to craft-dev or any
EKS-backed environment. Captures the deploy workflow, every concrete failure
mode encountered during the cc4a.95 rollout, and the institutional knowledge
about how the opencode-serve provider chain actually wires up at runtime.

**Status:** the deploy succeeded after the workarounds described below. The
underlying defects (RBAC gap, mutable-tag image cache, env-var refresh race)
are real and should be fixed in source rather than patched per-deploy.

---

## 1. The deploy workflow at a glance

### Triggering a build

The convention is a **git tag matching `experimental-cc4a.<N>`** pushed to
`origin`. Two GitHub workflows react to that pattern:

- `.github/workflows/deployment.yml` — main app images. `determine-builds`
  branches on `IS_EXPERIMENTAL_CC4A` and produces:
  - `onyxdotapp/onyx-backend-craft:experimental-cc4a.N` **and** `:craft-edge`
  - `onyxdotapp/onyx-web-server:experimental-cc4a.N` **and** `:craft-edge`
  - `onyxdotapp/onyx-model-server:experimental-cc4a.N` **and** `:craft-edge`
  - The regular `onyx-backend` is **NOT** built for experimental tags
    (`BUILD_BACKEND=false`).
- `.github/workflows/sandbox-deployment.yml` — separate workflow, same tag
  trigger. Builds `onyxdotapp/sandbox` if any path under
  `backend/onyx/server/features/build/sandbox/` changed since the previous
  `experimental-cc4a.*` tag. Output tags: `v0.1.X` (auto-incremented patch
  from the previous Docker Hub version tag) **and** `:latest` (mutable).

### Deploying

Two zsh helpers in `~/.zshrc`:

```zsh
alias use-craft='use-eks onyx-craft-dev us-west-2 && helm repo update'

upgrade-craft() {
  local VALUES_FILE=~/Documents/code/cloud-deployment-yamls/customers/onyx/craft-dev-values.yaml
  use-craft
  # … prompts y/N, then …
  helm upgrade onyx onyx/onyx -n onyx -f "$VALUES_FILE"
  # patch SAs:
  kubectl -n onyx patch deployment onyx-celery-worker-docfetching -p '…celery-worker-docfetching-sa…'
  kubectl -n onyx patch deployment onyx-api-server               -p '…onyx-workload-access…'
  # ensure rolebinding (idempotent):
  kubectl -n onyx-sandboxes create rolebinding celery-worker-sandbox-rolebinding \
    --role=api-server-role --serviceaccount=onyx:celery-worker-sandbox-sa 2>/dev/null || true
  # NEW (added during cc4a.95 deploy): reconcile api-server-role rules so the
  # opencode-serve transport's per-pod Secret writes don't 403:
  kubectl -n onyx-sandboxes patch role api-server-role --type=merge -p '{"rules":[…secrets+pods+services…]}'
  # rollout restart:
  kubectl -n onyx rollout restart deployment onyx-celery-worker-docfetching
  kubectl -n onyx rollout restart deployment onyx-api-server
}
```

The values file (`craft-dev-values.yaml`) controls `global.version` (which
resolves to `:craft-edge` for all chart-templated images via `pullPolicy:
Always`) and `configMap.SANDBOX_CONTAINER_IMAGE` (env var the api server
reads at sandbox-provision time).

---

## 2. Things that broke during cc4a.95 (in order hit)

### 2.1 RBAC gap: `secrets` not in `api-server-role`

**Symptom:**

```
{"detail":"Session creation failed: (403) Forbidden
secrets \"sandbox-<id>-opencode-auth\" is forbidden:
User \"system:serviceaccount:onyx:onyx-workload-access\" cannot
get resource \"secrets\" in API group \"\" in the namespace \"onyx-sandboxes\""}
```

**Root cause:** `api-server-role` (defined in
`cloud-deployment-yamls/danswer/role/api-server-role.yaml`, applied by
kustomize/Argo) only granted `pods`, `pods/exec`, and `services`. The
opencode-serve transport added a per-pod K8s Secret
(`sandbox-<id>-opencode-auth`) that the api server creates / reads /
deletes. The role never had `secrets` verbs.

**Fix:**

```yaml
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["create", "get", "list", "watch", "delete", "patch"]
```

Live on craft-dev: imperative `kubectl patch role api-server-role --type=merge
-p '{"rules":[…]}'` baked into `upgrade-craft` so subsequent deploys
self-heal. Single-tenant environment so Argo isn't reconciling this away.

**For a real multi-tenant or Argo-managed env:** the rule must land in the
chart / source-of-truth yaml (`onyx/onyx` helm chart's sandbox-rbac template
per onyx-cli's recommendation), otherwise the imperative patch gets undone
on the next Argo sync.

### 2.2 Mutable `:latest` tag + cached node images

**Symptom:** even after pushing a new `onyxdotapp/sandbox:latest`, freshly
provisioned sandbox pods kept running the **old** image. opencode-serve was
not listening on `:4096` and the entrypoint was just `sleep infinity` (the
prior placeholder behavior baked into the older image).

**Root cause:** sandbox pods are created with `imagePullPolicy: IfNotPresent`
(set in `kubernetes_sandbox_manager._create_sandbox_pod`, not overridable
via helm values). When the image reference is the mutable `:latest`, the
node sees "I already have an image with tag `:latest`" and skips the pull.
The chart-level `global.pullPolicy: Always` applies to chart-managed pods
(api server, web, etc.), NOT to imperatively-managed sandbox pods.

**Fix (chosen):** pin `SANDBOX_CONTAINER_IMAGE` to the **specific version
tag** in `craft-dev-values.yaml`:

```yaml
SANDBOX_CONTAINER_IMAGE: "onyxdotapp/sandbox:v0.1.45"
```

Because the image reference is new, the node MUST pull it even under
`IfNotPresent`. The convention is to bump this per cc4a.N deploy — look up
the corresponding `v0.1.X` on Docker Hub (sorted by `last_updated`).

**Real fix (deferred):** change the api server's sandbox pod spec to
`imagePullPolicy: Always` in `kubernetes_sandbox_manager._create_sandbox_pod`.
Avoids the per-deploy tag-bump dance.

### 2.3 `OPENCODE_CONFIG_CONTENT` env var doesn't refresh on Secret update

**Symptom:** opencode-serve kept reporting `Model not found:
anthropic/claude-opus-4-7` even after:
- adding `build-mode-anthropic` to the admin LLM providers,
- deleting the opencode-auth Secret,
- letting the api server re-provision it with multi-provider content
  (verified via `kubectl get secret … -o jsonpath='{.data.config}' |
  base64 -d` to show both `enabled_providers: ['anthropic', 'openai']`).

But `kubectl exec sandbox-… -- env | grep OPENCODE_CONFIG_CONTENT` still
showed the **old, openai-only** value.

**Root cause:** Kubernetes does not propagate Secret updates to env vars on
running pods. The Secret content changed; the pod's env was a snapshot from
when the container started. Container restart (process restart inside the
pod) reads cached env from the kubelet, not from the live Secret. Only
**pod deletion** forces a fresh env load from the current Secret.

**Symptom amplification:** opencode-serve reads `OPENCODE_CONFIG_CONTENT` env
var **directly at startup**. (Earlier hypothesis "it needs a file" was a red
herring — opencode does also probe filesystem paths but env-var-driven
config takes priority and is the path craft uses.) Stale env → stale
opencode provider registry. The api server's `_provision_opencode_secret`
rebuilds the Secret correctly, but no code path in the api server deletes
the pod after a Secret content change.

**Fix (manual recovery):** `kubectl delete pod sandbox-<id>` after any
admin/llm-provider change that should reach the sandbox. The api server's
existing reconciliation (health check fails → terminate → re-provision)
recreates the pod, which loads fresh env from the now-current Secret.

**Real fix (deferred):** when the api server detects that `all_llm_configs`
has changed vs. the deployed sandbox, it should delete the pod (forcing env
refresh), not just `replace_namespaced_secret`. A simpler version: any
admin LLM-provider mutation invalidates user sandboxes.

### 2.4 `_get_all_llm_configs` filter requires `build-mode-*` provider names

**Symptom:** admin had an Anthropic provider configured with `name:
"anthropic"`. opencode prompts for `providerID: anthropic` returned
`ProviderModelNotFoundError`. The sandbox's `OPENCODE_CONFIG_CONTENT` only
had `openai`.

**Root cause:** `fetch_all_build_mode_llm_providers`
(`backend/onyx/server/features/build/db/build_session.py`) filters with
`LLMProviderModel.name.like("build-mode-%")`. Providers without the
`build-mode-` name prefix are silently dropped during sandbox provisioning.

**Fix:** add a SECOND `LLMProvider` row with name `build-mode-anthropic`
(provider type still `anthropic`, same API key, same visible models).
Optionally also `build-mode-openai`.

**Why the prefix?** The pattern allows non-craft LLM providers (the regular
chat product) and the craft-mode set to coexist without bleeding API keys
or model visibility across products. The prefix is the discriminator.

### 2.5 `_get_all_llm_configs` de-dups by `provider` type, not by row

When the user's BuildSession has `agent_provider="anthropic"`, the default
`llm_config` IS anthropic. `_get_all_llm_configs`:

```python
configs = [default]
seen_providers = {default.provider}  # {"anthropic"}
for provider in fetch_all_build_mode_llm_providers(db):
    if provider.provider in seen_providers:  # build-mode-anthropic → "anthropic" → skip
        continue
    …
```

→ the multi-provider list ends up with just `[anthropic_config]` because
the only other `build-mode-*` row is also anthropic. If `build-mode-openai`
existed, the list would have both — but only if you're NOT defaulting to
openai (in which case you'd lose anthropic from the seen-providers skip).

**Practical implication:** to have a sandbox with BOTH providers
preloaded, you need:
- Two `build-mode-*` providers in admin (different `provider` types), AND
- Either the user picks the one that's NOT the system default OR the
  system default picks one and the other is added by the build-mode loop.

### 2.6 Bus self-close residue (pre-fix, captured during this work)

Already shipped in `51b780b9f8` — `PodEventBus.closed` property + eviction
in `_get_or_create_event_bus`. Mentioning it here so future agents
inspecting the bus lifecycle understand the existing safety net.

### 2.7 Cold-pod connection errors during ensure_session

Already shipped in `e6e8a109e9` — 3-attempt retry with linear backoff on
`httpx.ConnectError`/`RemoteProtocolError` in `_http_with_cold_pod_retry`.
Subsequently tightened in `28fd724314` — POST `/session` retries only on
`ConnectError` (not `RemoteProtocolError`) to avoid orphan-session leak.

---

## 3. How the opencode provider chain actually wires up

This is the load-bearing institutional knowledge. Without it, the chain
above looks like a random pile of subsystems. With it, the bugs become
obvious in advance.

### 3.1 End-to-end data flow

1. **Admin UI** → `llm_provider` rows in Postgres. The `name` field
   controls whether the row participates in craft (`build-mode-*`
   pattern). `provider` is the type (`anthropic`, `openai`, `openrouter`).
2. **BuildSession created** → `agent_provider` / `agent_model` on the row
   record the user's selection. Defaults: `fetch_default_llm_model()`.
3. **Sandbox provisioning** (`KubernetesSandboxManager.provision`):
   - `_get_llm_config(requested_provider_type, requested_model_name)`
     resolves the **default** for this sandbox. Tries
     `fetch_llm_provider_by_type_for_build_mode(provider_type)` first,
     which looks for `build-mode-{type}` then falls back to any provider
     with that type. Returns an `LLMProviderConfig`.
   - `_get_all_llm_configs(default=llm_config)` builds the full list:
     `[default]` + every other `build-mode-*` provider whose `provider`
     type isn't already in `seen_providers` and that has at least one
     `is_visible=True` model.
   - `build_multi_provider_opencode_config(providers, default_provider,
     default_model, disabled_tools)` produces the opencode.json shape:
     `{$schema, model, provider: {<type>: {options.apiKey, models}}, …,
     enabled_providers, permission}`.
   - The JSON is `json.dumps`'d and written to a per-pod K8s Secret
     (`sandbox-<id>-opencode-auth`, key `config`) alongside the per-pod
     `password` (HTTP Basic auth for opencode).
4. **Pod spec** references the Secret via two `secretKeyRef` env entries:
   `OPENCODE_CONFIG_CONTENT` and `OPENCODE_SERVER_PASSWORD`. **k8s does
   NOT propagate Secret updates to running pod envs** — see §2.3.
5. **Entrypoint** (`entrypoint.sh`) runs `opencode serve --hostname 0.0.0.0
   --port "$OPENCODE_SERVE_PORT" --print-logs` in a `while true` restart
   loop. It does NOT write `OPENCODE_CONFIG_CONTENT` to a file (the env
   var is the source of truth for opencode; opencode also probes file
   paths but the env-var path is what we use).
6. **opencode-serve** registers providers **lazily** on the first prompt:
   `service=provider status=started state` → `service=provider
   providerID=<X> found` per registered provider →
   `service=provider status=completed`. Missing `found` log lines for a
   provider = silently dropped. The catalog suggestions list bundled
   model IDs without provider prefix.
7. **Per-prompt model override**: api server's `_post_prompt_async` sets
   `body["model"] = {"providerID": …, "modelID": …}` when both are set on
   the BuildSession. opencode looks up `providerID/modelID` in its merged
   registry. If the providerID isn't registered → `ProviderModelNotFoundError`.

### 3.2 Auth

- `OPENCODE_SERVER_USERNAME = "opencode"` (constant in `configs.py`). Not
  `"onyx"` — this tripped up curl-based debugging.
- Password comes from `OPENCODE_SERVER_PASSWORD` env (mounted from
  Secret). Both the api server (HTTP Basic from the cluster) and curl
  from inside the pod (`-u "opencode:$OPENCODE_SERVER_PASSWORD"`) need
  this exact user.

### 3.3 Common error signatures and what they mean

| Error / log line | Meaning |
|---|---|
| `secrets … is forbidden … namespace "onyx-sandboxes"` | §2.1 — `api-server-role` missing `secrets` verbs |
| `[Errno 111] Connection refused` on POST `/session` | opencode-serve not bound to `:4096`. Cold pod, crashloop, or process death |
| `ProviderModelNotFoundError` w/ bundled-model suggestions | Provider not registered in opencode (silent drop from config file/env), or config not loaded |
| `Sandbox … has status provisioning and is being created by another request` | Intentional guard, predates this branch. Two concurrent requests on the same user's mid-provision sandbox |
| Sandbox pod shows old behavior despite new image push | Cached `:latest` digest on the node + `IfNotPresent` policy (§2.2) |
| `kind=Pod … Reusing existing sandbox …` but pod doesn't exist | DB row says RUNNING; reconciliation needs to fire (health check) |
| opencode serve restarts in tight loop, exit 143 | SIGTERM propagated from entrypoint trap. Almost always operator-induced (`pkill opencode` from inside the pod) |

### 3.4 Diagnostic snippets

**What providers does THIS sandbox have?**
```bash
SBX=$(kubectl --context onyx-craft-dev -n onyx-sandboxes get pods -o name | head -1 | sed 's|pod/||')
kubectl --context onyx-craft-dev -n onyx-sandboxes exec "$SBX" -c sandbox -- sh -c 'echo "$OPENCODE_CONFIG_CONTENT"' \
  | python3 -c 'import sys, json; d=json.load(sys.stdin); print("enabled:", d.get("enabled_providers")); print("keys:", list(d.get("provider",{}).keys()))'
```

**What providers does opencode actually think it loaded?** Watch the logs
for `service=provider providerID=<X> found`. If a provider is in the env
var but missing from this log, opencode silently dropped it.

**What does `_get_all_llm_configs` return RIGHT NOW for a given default?**
```bash
kubectl --context onyx-craft-dev -n onyx exec deploy/onyx-api-server -- python -c "
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
url = f'postgresql+psycopg2://{os.environ[\"POSTGRES_USER\"]}:{os.environ[\"POSTGRES_PASSWORD\"]}@{os.environ[\"POSTGRES_HOST\"]}:{os.environ.get(\"POSTGRES_PORT\",\"5432\")}/{os.environ[\"POSTGRES_DB\"]}'
engine = create_engine(url)
with Session(engine) as db:
    from onyx.server.features.build.session.manager import SessionManager
    sm = SessionManager(db)
    default = sm._get_llm_config(None, None)
    print('default:', default.provider, default.model_name)
    for c in sm._get_all_llm_configs(default=default):
        print(f'  provider={c.provider!r} model={c.model_name!r} has_key={bool(c.api_key)}')
"
```

**Test the opencode API directly** (auth is `opencode:$OPENCODE_SERVER_PASSWORD`):
```bash
kubectl … exec sandbox-… -c sandbox -- sh -c '
curl -s -u "opencode:$OPENCODE_SERVER_PASSWORD" http://localhost:4096/doc | python3 -m json.tool | head -20
'
```

**Tail opencode logs:**
```bash
kubectl --context onyx-craft-dev -n onyx-sandboxes logs -f sandbox-<id> -c sandbox
# or with stern:
stern --context onyx-craft-dev -n onyx-sandboxes sandbox -c sandbox
```

---

## 4. Recovery recipes

### Symptoms cluster A: "my admin LLM provider isn't reaching the sandbox"

1. Confirm provider has `name LIKE 'build-mode-%'`:
   ```sql
   SELECT id, name, provider, default_model_name FROM llm_provider;
   ```
   If not, rename (or duplicate). `provider` field stays as the type.
2. Confirm at least one `model_configuration` has `is_visible=true` for
   the provider — silently skipped otherwise.
3. Delete the user's sandbox pod (forces env refresh from the Secret).
   The api server's reconciliation will re-provision with the new provider list.
4. Tail opencode logs for `service=provider providerID=<X> found` after
   the first prompt. If not there, the provider got dropped silently —
   recheck the JSON shape in OPENCODE_CONFIG_CONTENT.

### Symptoms cluster B: "new sandbox image isn't being used"

1. Check the pod's actual imageID:
   ```bash
   kubectl -n onyx-sandboxes get pod sandbox-<id> -o jsonpath='{.status.containerStatuses[?(@.name=="sandbox")].imageID}'
   ```
2. Compare with Docker Hub `:latest` digest (look up via the Docker Hub
   API or the registry-mirror).
3. If digests differ, the node has a cached older image and the pod is
   running that. Pin `SANDBOX_CONTAINER_IMAGE` to a specific version
   (`v0.1.X`) in `craft-dev-values.yaml`, re-run `upgrade-craft`, delete
   the pod.

### Symptoms cluster C: "RBAC 403 on a sandbox-namespace resource"

Re-run `upgrade-craft` — its `kubectl patch role` step is idempotent. If
the error persists, compare the current role rules against what the api
server actually calls (grep for the k8s client method names in
`kubernetes_sandbox_manager.py`).

---

## 5. Architectural follow-ups (none blocking, all on the table)

| Item | Why it matters | Where to land it |
|---|---|---|
| `imagePullPolicy: Always` on sandbox pods | Eliminates the `:latest` cache trap so deploys don't need a per-version tag bump | `kubernetes_sandbox_manager._create_sandbox_pod` |
| Recreate pod on Secret content change | Fixes §2.3 — env doesn't refresh on Secret update | `_provision_opencode_secret` or `_provision_sandbox` |
| Chart-managed sandbox RBAC | Move §2.1's role into the helm chart so multi-tenant Argo doesn't undo the patch | onyx helm chart's sandbox-rbac template |
| Pre-seed `build-mode-*` providers in admin onboarding | Avoid the silent-skip filter trap | Onyx admin / setup wizard |
| Surface "sandbox provisioning" via 409 + Retry-After | Instead of `RuntimeError` → JSON dump, return a clean wait/retry signal that the FE can poll on | `session/manager._stream_cli_agent_response` |

---

## 6. Provenance

Captured during the cc4a.95 deploy on 2026-05-25/26 against `onyx-craft-dev`
(us-west-2 EKS). Reference branch: `craft/opencode-serve-transport`. The
imperative recovery commands documented here all ran successfully against
that environment; the source-of-truth fixes are tracked in the followups
table above.
