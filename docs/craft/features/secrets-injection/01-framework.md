# Plan 1 — Egress Credential-Injection Seam

This is the foundation of the Craft secret-injection workstream: keep long-lived secrets (LLM
provider keys, the Onyx PAT) **out of the sandbox pod** and hold them only in the egress proxy.
The sandbox is a low-trust environment that runs agent-authored code, so it shouldn't hold
credentials at rest; the proxy (`backend/onyx/sandbox_proxy/`) is a separate, locked-down
Deployment that already forces all egress through itself, MITMs TLS with a CA the sandbox trusts,
and resolves sandbox identity by source IP — the natural place to broker secrets.

It defines **one** egress credential-injection seam, **shared with the external-apps work**
(Danelegend, PRs #11033–#11413). External-app credentials, LLM keys, and the Onyx PAT all inject
through it. The workstream is three plans: this seam, then the [Onyx PAT resolver](./02-onyx-pat.md)
and [LLM provider-key resolver](./03-llm-key.md), which plug into it and are independent of each
other.

## Landing plan (PRs)

Roughly one PR per plan, flag-gated and independently revertible:

1. **Prerequisite** — wire `ENCRYPTION_KEY_SECRET` into the proxy Deployment.
2. **This seam** — interface + dispatcher + rendering helper + config + observability; lands inert
  (no resolvers registered).
3. **[Onyx PAT resolver](./02-onyx-pat.md)** and 4. **[LLM key resolver](./03-llm-key.md)** — each one
  atomic, flag-gated PR (placeholder + resolver + routing together). Independent; land in parallel.

Sequence: 1 + 2 first, then 3 and 4 in parallel. Each migration must ship atomically behind its
flag — the pod-side placeholder only takes effect once its resolver is live. The external-apps
convergence (retire `action_matcher.py`, register Dane's resolver) is a separate PR in that track.

## Issues to Address

Two secrets are currently provisioned into the pod: the LLM key in `OPENCODE_CONFIG_CONTENT`, and
the Onyx PAT in the `ONYX_PAT` env var (both in `kubernetes_sandbox_manager.py`). This seam relocates
them to the proxy so they no longer reside in the sandbox. Separately, the external-apps work already resolves per-user app
credentials server-side — `get_external_app_credentials(db, user_id, url)` (added in the open PR
#11086) matches the outbound URL against an app's `upstream_url_patterns` and renders its
`auth_template`; the skill wrappers send no auth — and expects the proxy to inject them. **But the
proxy injection step doesn't exist yet, for anyone.** Both efforts need the same primitive; building
them as separate request-hook paths would collide over the same headers. This plan builds the one
seam; the LLM/PAT resolvers (plans 2 & 3) and Dane's external-app resolver plug into it. It can land
with zero resolvers (pure substrate).

## Important Notes

**Trust boundary, already in place.** All egress is iptables-forced through the proxy
(`firewall-init.sh`); its NetworkPolicy only admits the sandbox namespace; it MITMs TLS; and
`IdentityResolver.resolve_sandbox(src_ip)` (`identity.py`) yields `ResolvedSandbox` (`sandbox_id`,
`user_id`, `tenant_id`, …). `GateAddon` already has a `db_session_factory` (`server.py`).

**One dispatcher, many resolvers.** Define `CredentialResolver.resolve(request, identity) -> Injection | None`: return rendered auth headers to set; `None` if the host doesn't match (pass
through); or signal **block** (fail-closed) if the host matches but the secret can't be resolved.
Three resolvers plug in:

- **ExternalAppResolver** — Dane's, per-**user** (creds are per-user), from `external_app` rows.
- **LLMProviderKeyResolver** — per-**tenant** (sandboxes share the tenant's keys), from `llm_provider`.
- **OnyxPatResolver** — per-**sandbox** (each sandbox has its own PAT).

The dispatcher resolves identity once, passes the full `ResolvedSandbox`, and tries resolvers
first-match-by-host. Hosts are disjoint (external-app hosts vs LLM provider hosts vs the Onyx API
host), so this is conflict-free; if an overlap ever surfaces, fix the order explicitly.

**Reuse the external-apps matching + rendering contract.** An `external_app` models
`upstream_url_patterns` (regex) + `auth_template` (a `{header: "Bearer {token}"}` dict rendered via
`format_map`, fail-closed on any missing placeholder). LLM/PAT resolvers supply their templates and
values from code rather than DB rows, but the render-and-overwrite step is identical. Don't build a
parallel matcher — the current `sandbox_proxy/action_matcher.py` is a stopgap to be retired (step 6).

**Placeholder/overwrite contract (single source — referenced by plans 2 & 3).** Clients need a
*non-empty* credential to build a request (onyx-cli treats empty as "unconfigured"; opencode's AI
SDK throws if the key is unset). So the pod ships a fixed, non-secret **placeholder constant** in
place of each real credential, and the proxy **overwrites** the auth header(s) named in the resolved
template — set/replace, never append; all other headers (e.g. Anthropic's `anthropic-version`) left
intact. Overwrite is unconditional for matched hosts; the proxy doesn't need to recognize the
placeholder value. A resolver may match one host or several.

**Decryption: `ENCRYPTION_KEY_SECRET` on the proxy (prerequisite, step 1).** The proxy decrypts DB
columns with the same machinery as the api_server (`EncryptedString`, `LLMProviderView.from_model`);
no-op in MIT, real in EE/cloud. Trade-off: it can now decrypt any encrypted column it can reach, so
its access surface matters more. **Coordination flag:** external-app creds are stored plaintext
today (unlike `llm_provider.api_key` and the PAT) — encrypt them with Dane if we're hardening this.

**Inject at `requestheaders` (single source for streaming-safety).** Injection only rewrites a
request header, so the dispatcher runs in `requestheaders` — headers and source IP are available
before the body. It never reads the request body or the response, so large prompts and SSE
responses pass through untouched. A matched+injected flow is flagged in `flow.metadata` (mirroring
the snapshot stream flag) so the `request` hook skips the stopgap gating path.

**Compose with policy/approval gating.** Hook order: resolve identity → policy decision → inject
(only if allowed) → forward. Dane's #11366 adds `ALWAYS`/`ASK`/`DENY` policy + an action catalog
the proxy will consume, routing `ASK` through the existing approval flow. Injection and policy are
separate concerns at the same hook.

**Coordination / ownership.** The seam lives in `sandbox_proxy/` (ours): we own the dispatcher, the
`CredentialResolver` interface, the fail-closed/ordering contract, and the LLM/PAT resolvers; Dane
owns the ExternalAppResolver. Agree the interface before either side builds the injection step.

## Implementation Strategy

1. **Wire `ENCRYPTION_KEY_SECRET` into the proxy Deployment (prerequisite — land first).** From the
  same K8s Secret the api_server uses.
2. **Define `CredentialResolver` + the dispatcher** in a new module `sandbox_proxy/injection/`. The
  dispatcher holds an ordered resolver list, is constructed in `server.py`, and is passed to
   `GateAddon` like `snapshot_policy`. It runs in `requestheaders`: first host match wins → render +
   overwrite headers → flag the flow to skip gating. Matched-but-unresolvable → block via the
   existing 403 helper; unmatched → pass through. Reuse the resolved `ResolvedSandbox`; keep
   injection independent of gating.
3. **Shared rendering helper** — `auth_template` `format_map`, fail-closed — used by all resolvers.
4. **Config.** A seam enable flag plus per-resolver flags (e.g. `*_INJECTION_ENABLED`), read at
  startup like `SnapshotEgressPolicy.from_env()`, so plans 2 & 3 and Dane's apps roll out
   independently.
5. **Observability.** A structured log per injection (host, sandbox_id, tenant_id, resolver, result)
  — never the secret value.
6. **Converge with external apps.** Support Dane adapting `get_external_app_credentials` into a
  `CredentialResolver`; retire `sandbox_proxy/action_matcher.py` for his #11366 catalog.

## Tests

External-dependency unit tests (proxy + DB real, sandbox mocked — matches the existing
`sandbox_proxy/` suite):

- Matched request → target header **overwritten** (not duplicated), other headers intact; unmatched
host passes through.
- Fail-closed: matched host with an unresolvable secret → 403, not forwarded.
- Multiple resolvers registered → first host match wins; an injected flow skips the gating path.
- Identity: the resolver receives the correct `ResolvedSandbox` for the source IP.
- Feature-flag off → no-op.

Don't test mitmproxy's header API or Pydantic ([[feedback_dont_test_framework_validation]]).
Per-resolver behavior is exercised by plans 2/3 and Dane's tests.

## Out of scope

- Removing `ONYX_PAT` / the LLM key from the pod — plans 2 and 3.
- The ExternalAppResolver and external-app credential encryption — Dane's, coordinated.
- Policy enforcement (#11366) — composes at the same hook but is separate.
- PAT scopes (`plans/whuang/pat_system/SCOPES.md`, unimplemented).

