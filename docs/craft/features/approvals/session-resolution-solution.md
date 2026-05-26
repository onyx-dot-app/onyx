# Session Resolution — In-Band Identity via opencode `shell.env`

How the egress proxy can recover the **exact** originating `BuildSession`
for a gated request, instead of guessing with the most-recent-active
heuristic. This is the concrete answer to the open question left dangling
in [session-resolution-issues.md](./session-resolution-issues.md) §"Per-session
port becomes harder", option (a): *"opencode itself setting a per-session
identity when it spawns skill subprocesses (unclear whether opencode supports
this)."*

It does — via the `shell.env` plugin hook. But the obvious key (the working
directory) does **not** work on the serve transport because of a directory-
routing gap documented below. The workable key is the opencode **session id**,
mapped to `BuildSession.opencode_session_id`.

## TL;DR

opencode rebuilds the child-process environment on **every** shell/bash/pty
invocation and runs a plugin hook (`shell.env`) while doing so. The hook
receives `ctx.sessionID` — the opencode session being prompted. A single
pod-wide plugin stamps that id onto each outbound request as **proxy
credentials**; the proxy maps it (`BuildSession.opencode_session_id`) to the
exact `BuildSession`, cross-checked against the src-IP → user/sandbox anchor.
No per-session ports, no per-session UIDs, no `last_activity_at` race.

The id rides in `Proxy-Authorization`, which is hop-by-hop: the proxy consumes
it and it never reaches the origin (Slack etc.), so it does not collide with
the real `Authorization` credential the proxy injects in Phase 2.

This is **cooperative** identity (userland env, not kernel-enforced), so it
does not replace the strict per-session-UID design for an adversarial-agent
threat model. It does solve the stated v0 problem: routing the card to the
right chat tab when an interactive session and a scheduled-task session are
active on the same sandbox at once.

> **Why session id and not cwd?** See [§Why not cwd](#why-not-cwd-the-serve-directory-gap).
> On the serve transport, every session currently resolves to the same
> working directory (`process.cwd()` of `opencode serve`), so cwd cannot
> distinguish sessions. `ctx.sessionID` is correct regardless.

## Why this beats the v0 heuristic

| | v0 heuristic (shipped) | This proposal |
|---|---|---|
| Identity source | src-IP → user → most-recent-active session | src-IP → user (anchor) **+** session id in `Proxy-Authorization` |
| Concurrent same-user sessions | races on `last_activity_at`; card may land in wrong tab | exact; each request names its own session |
| Relies on scheduled-task serialization for routing correctness | yes (`phase-1-proxy.md` T1.4 note) | no |
| Per-session infra (ports / UIDs) | none | none |
| Enforcement | n/a | cooperative (see §Trust model) |

## The opencode mechanism (verified against the opencode tree)

Citations are into the opencode repo (`anomalyco/opencode`, `packages/opencode`).

### `shell.env` fires per command, with the session id

`tool/shell.ts:412-422` — the bash tool builds the spawned process env fresh,
merging plugin output over `process.env`:

```ts
const shellEnv = Effect.fn("ShellTool.shellEnv")(function* (ctx, cwd) {
  const extra = yield* plugin.trigger(
    "shell.env",
    { cwd, sessionID: ctx.sessionID, callID: ctx.callID },   // <- sessionID is the key
    { env: {} },
  )
  return { ...process.env, ...extra.env }   // hook output wins
})
```

- Called per command at `tool/shell.ts:637`, inside `execute()` which runs
  once per tool call with its own `ctx`.
- The merged env is handed straight to the child at `tool/shell.ts:289`
  (`ChildProcess.make(..., { cwd, env })`).
- The direct shell endpoint goes through the same hook with the same fields
  (`session/prompt.ts:617`). The PTY path also calls `shell.env`
  (`pty/index.ts:196`) but passes only `{ cwd }` — see the PTY caveat below.

**Concurrency is safe by construction.** `sessionID` is passed as an argument
per invocation and the env object is local to that spawn. Two sessions issuing
commands simultaneously each build their own env from their own `ctx.sessionID`.
There is no shared mutable state to race — which is exactly the property the
heuristic lacks.

### Hook surface

`shell.env` is a documented, stable hook
(`skill/prompt/customize-opencode.md:272-287`). A plugin is an async factory
returning hook callbacks (`…:257-269`). Plugins are declared via the `plugin`
array in opencode config, which accepts an npm name **or a file path**
(`config/plugin.ts:10-13`).

## Why not cwd — the serve directory gap

The natural key would be the per-session working directory
(`…/sessions/<build_session_id>/`, `sandbox/base.py:85-98`). On the **serve
transport this does not work**, because the session's directory never reaches
the instance context that the bash tool reads. Traced end to end:

1. The serve client sends the dir only in the **POST /session body**:
   `body = {"directory": cwd}` (`sandbox/opencode/serve_client.py:815`), with
   no query param and no `x-opencode-directory` header (httpx client sets
   neither — `serve_client.py:696-706`).
2. opencode decodes that body as `Session.CreateInput`
   (`server/.../groups/session.ts:201`), and **`CreateInput` has no `directory`
   field** (`session/session.ts:243-252`) — the key is silently stripped. The
   session is created with `directory: ctx.directory` from the *route* context
   (`session/session.ts:665-669`).
3. The route directory resolves as
   `?directory=` ∥ `x-opencode-directory` ∥ **`process.cwd()`**
   (`server/.../middleware/workspace-routing.ts:87`). The client sets neither
   of the first two, so it is always `process.cwd()`.
4. Prompt requests carry no directory either, and nothing re-provides instance
   context from the session's stored `directory`. The bash tool reads
   `cwd = InstanceState.context.directory` (`tool/shell.ts:612`,
   `session/prompt.ts:572`) = `process.cwd()`.

**Net: every session on a pod resolves to the single `process.cwd()` of the
`opencode serve` process.** The `shell.env` hook therefore receives an
identical `cwd` for all sessions, while `ctx.sessionID` stays correct. Hence we
key on session id.

This is consistent with the serve design already treating config as pod-wide
via `OPENCODE_CONFIG_CONTENT` and *not* writing per-session `opencode.json`
(`kubernetes_sandbox_manager.py:1623-1625`). See
[§Adjacent bug](#adjacent-bug-session-isolation) — the directory collapse is
very likely an unintended side effect worth fixing independently.

## The identity key: opencode session id → BuildSession

The serve migration persists `BuildSession.opencode_session_id` (the opencode
session created by `ensure_session`, see
[opencode-serve-client.md](../opencode-serve-client.md)). So the hook injects
`ctx.sessionID`, and the proxy resolves:

```
BuildSession  WHERE opencode_session_id == <sessionID from Proxy-Authorization>
```

cross-checked against the IP anchor (next section). This is a stable 1:1
mapping and needs no directory.

**Sub-agent caveat.** A `task` sub-agent runs under a *child* opencode session
with its own `sessionID` and a `parentID`. Child ids are not in
`opencode_session_id`, so a sub-agent's egress won't map directly — and cwd
can't rescue it either (still pod-wide). Handle it as step 3 below (heuristic
fallback over the IP anchor's user), or, if sub-agent egress must be exact,
have the plugin resolve the root session via the opencode SDK client
(`PluginInput.client`) and cache `child → root`. Defer unless craft actually
fans out sub-agents that make gated calls.

## The carrier: `Proxy-Authorization`, not the request's `Authorization`

The plugin replaces the proxy URL's userinfo so the session id travels as proxy
basic-auth. Phase 1 already sets a static `HTTPS_PROXY`/`HTTP_PROXY` pointing at
`http://sandbox-proxy:<port>` (`phase-1-proxy.md` T1.3). The hook rewrites it to
carry credentials:

```
HTTPS_PROXY = http://<opencode_session_id>:<per-pod-proxy-secret>@sandbox-proxy:<port>
```

What the proxy sees:

- **HTTPS (Slack, the common case):** the client issues
  `CONNECT api.slack.com:443` carrying
  `Proxy-Authorization: Basic base64(<sid>:<secret>)`. That header is on the
  *tunnel setup*, separate from the TLS-encrypted inner request. It never
  reaches Slack.
- **Plain HTTP:** `Proxy-Authorization` is hop-by-hop (RFC 7235); the proxy
  consumes it and does not forward it.

Either way the session tag does **not** land on the request's own
`Authorization` header — so it composes cleanly with Phase-2 credential
injection:

| Header | Set by | Consumed by | Forwarded to origin? |
|---|---|---|---|
| `Proxy-Authorization` | `shell.env` plugin (session tag) | the proxy | No |
| `Authorization` | the proxy (Phase 2 cred injection) | origin (Slack) | Yes |

## Proxy-side changes (extends Phase 1 `IdentityResolver`)

`IdentityResolver.resolve()` (`sandbox_proxy/identity.py`, `phase-1-proxy.md`
T1.4) gains a header-first path. Source-IP resolution stays as the **trust
anchor**; the header only disambiguates *which session of the already-resolved
user/sandbox*.

```
resolve(src_ip, proxy_auth_user, proxy_auth_pass) -> SessionContext | None:
  1. anchor = SandboxIPLookup(src_ip)          # IP → sandbox + tenant + user  (trusted)
     if anchor is None: return None            # unidentified; Phase 2 gate rejects

  2. if proxy_auth_user:                        # opencode session id
       bs = BuildSession.by_opencode_session_id(proxy_auth_user)
       if bs is not None
          and bs.user_id == anchor.user_id            # same user as the IP anchor
          and bs.sandbox_id == anchor.sandbox_id       # same sandbox as the IP anchor
          and (optional) constant_time_eq(proxy_auth_pass, per_pod_secret(anchor)):
            return SessionContext(session=bs, ...anchor...)   # EXACT

  3. # no/invalid header (opencode's own LLM calls, sub-agent child sessions,
     # non-shell egress, tampering): fall back to most-recent-active heuristic
     # over anchor.user_id  — i.e. today's behavior.
```

- Step 1 is unchanged and remains the security boundary: a sandbox cannot spoof
  its source IP, so it cannot claim another user's/sandbox's identity.
- Step 2 is the precise win. The cross-checks bound any header tampering to
  *within the same user+sandbox* — strictly no worse than today, exact in the
  honest case.
- Step 3 keeps the system correct for traffic that legitimately carries no
  resolvable tag and preserves the v0 floor.

`PassthroughAddon` (`phase-1-proxy.md` T1.5) and the Phase-2 `GateAddon` read
`flow.request.headers["Proxy-Authorization"]` (mitmproxy surfaces CONNECT auth
on the flow) and pass the parsed username/password into `resolve()`.

## Coverage — what gets an exact tag and what doesn't

| Egress source | Carries session tag? | Resolution |
|---|---|---|
| Skill/bash subprocess (`curl`, `python`, CLI) — **the gated actions** | Yes (`shell.env`, `ctx.sessionID`) | Exact (step 2) |
| Direct `/session/{id}/shell` endpoint | Yes (`prompt.ts:617`) | Exact (step 2) |
| PTY / terminal | Tag only if extended (see PTY caveat) | Exact or heuristic |
| `task` sub-agent subprocess egress | Child session id — not in `opencode_session_id` | Heuristic (step 3) unless parent-resolved |
| opencode-serve's own LLM/provider calls | No (in-process, not a shell) | Heuristic (step 3) — not user-cred-injected |
| opencode in-process `webfetch` | No (in-process) | Heuristic (step 3) |

**PTY caveat:** `pty/index.ts:196` calls `shell.env` with only `{ cwd }`, no
`sessionID`. A `shell.env` hook keyed on `ctx.sessionID` will get `undefined`
for PTY-spawned egress and fall to step 3. If craft routes gated actions
through the PTY path, either (a) extend the plugin to also honor any
session-bearing env the PTY layer sets, or (b) accept heuristic fallback for
PTY. Bash-tool egress (the normal skill path) is unaffected.

## Trust model

- **Anchor (strong):** src-IP → sandbox → user. Kernel/informer-enforced; the
  agent cannot forge its packet source IP. This bounds everything.
- **Tag (cooperative):** the session id in `Proxy-Authorization` is a userland
  env var. A malicious or buggy process inside the sandbox could overwrite
  `HTTPS_PROXY` and substitute a *different* session id — but the cross-checks
  in step 2 confine that to the same user+sandbox. Cross-user/cross-tenant
  impersonation is impossible because the IP anchor wins.
- **Optional hardening:** include a per-pod proxy secret as the password
  component (provisioned alongside `OPENCODE_SERVER_PASSWORD`,
  [opencode-serve-client.md](../opencode-serve-client.md) §Decision 2) and
  verify it constant-time, or HMAC the session id with it. This detects tag
  forgery from a process that doesn't know the secret. It does not make the
  scheme strict (the secret lives in the same pod env the agent runs in) — for
  strict identity see the per-session-UID design in
  [session-resolution-issues.md](./session-resolution-issues.md). This proposal
  is the precise-but-cooperative middle the "per-session port" alternative was
  reaching for, achieved in-band without port allocation.

## The plugin (sketch)

One pod-wide plugin. It is stateless and keys on `ctx.sessionID`.

```ts
// /opt/onyx/opencode-plugins/session-proxy-tag.ts
import type { Plugin } from "@opencode-ai/plugin"

const HOST   = process.env.SANDBOX_PROXY_HOST                 // e.g. "sandbox-proxy"
const PORT   = process.env.SANDBOX_PROXY_PORT
const SECRET = process.env.SANDBOX_PROXY_TAG_SECRET ?? "x"    // per-pod; optional hardening

export default (async () => ({
  "shell.env": async ({ sessionID }, output) => {
    if (!sessionID || !HOST || !PORT) return     // leave the static HTTPS_PROXY untouched
    const url = `http://${encodeURIComponent(sessionID)}:${SECRET}@${HOST}:${PORT}`
    output.env.HTTP_PROXY  = output.env.HTTPS_PROXY  = url
    output.env.http_proxy  = output.env.https_proxy  = url   // lowercase variants too
    // NO_PROXY and the CA-bundle env vars are already set by firewall-init (T1.3);
    // do not clobber them here.
  },
})) satisfies Plugin
```

Notes:
- It only *adds userinfo* to the host:port Phase 1 already configured; it does
  not invent a new proxy target, so the iptables lockdown (T1.3) still permits
  the connection.
- It deliberately does **not** touch `NO_PROXY` or the CA-bundle vars
  (`NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, …) — set once by
  `firewall-init.sh` and inherited via `process.env`.

## Wiring

1. **Ship the plugin file** in the sandbox image (e.g.
   `/opt/onyx/opencode-plugins/session-proxy-tag.ts`).
2. **Register it pod-wide** by adding its absolute path to the `plugin` array of
   the config surfaced as `OPENCODE_CONFIG_CONTENT` — i.e. the dict built by
   `build_multi_provider_opencode_config`
   (`kubernetes_sandbox_manager.py:1331`, env wired at `:658`). This is the only
   correct layer on serve: there is one pod-wide instance and per-session
   `opencode.json` is not written on serve
   (`kubernetes_sandbox_manager.py:1623-1625`). Add:
   ```python
   config["plugin"] = ["/opt/onyx/opencode-plugins/session-proxy-tag.ts"]
   ```
   (Confirm `OPENCODE_CONFIG_CONTENT` honors a file-path `plugin` entry; it is
   merged as a config source, so it should — verify with a one-time
   `plugin loaded` log line on serve boot.)
3. **Provide env:** `SANDBOX_PROXY_HOST` / `SANDBOX_PROXY_PORT` already exist on
   the sandbox container (`phase-1-proxy.md` T1.3); add `SANDBOX_PROXY_TAG_SECRET`
   only if adopting the hardening option.
4. **Proxy:** extend `IdentityResolver.resolve()` per §Proxy-side changes and
   have the addons pass the parsed `Proxy-Authorization` through.

## Tasks

- **TS.1** — Plugin file + image bake + registration into `OPENCODE_CONFIG_CONTENT`
  (steps 1–3). Verify the serve instance loads it (one-time `plugin loaded`
  log; confirm with a temp hook that writes a sentinel env var observed in a
  bash command).
- **TS.2** — `IdentityResolver` header-first path keyed on
  `opencode_session_id`, with `user_id` + `sandbox_id` cross-checks and
  heuristic fallback. Unit-test: exact match; wrong-user header → falls back
  (no leak); malformed/absent header → falls back.
- **TS.3** — Addons (`passthrough`, Phase-2 `gate`) read and forward
  `Proxy-Authorization`. Confirm mitmproxy exposes CONNECT auth on the flow for
  the HTTPS path.
- **TS.4** — (optional) per-pod tag secret generation/verification next to
  `OPENCODE_SERVER_PASSWORD`.
- **TS.5** — Integration: two concurrent sessions on one sandbox each
  `curl https://api.slack.com/...`; assert the proxy logs the **correct**
  distinct `BuildSession` per flow (independent of `last_activity_at`).

## Definition of done

- Two sessions active on one sandbox, both issuing egress: each request resolves
  to its own `BuildSession` at the proxy, demonstrably independent of
  `last_activity_at`.
- A request with a forged/foreign session id in `Proxy-Authorization` does
  **not** resolve to another user's session — it falls back to the IP anchor's
  heuristic (cross-user impossible).
- opencode's own LLM/provider egress still resolves via the IP anchor (step 3).
- Slack credential injection (Phase 2) is unchanged: the injected
  `Authorization` header is independent of the `Proxy-Authorization` tag.

## Adjacent bug: session isolation

The directory-routing gap in [§Why not cwd](#why-not-cwd-the-serve-directory-gap)
is not just an obstacle to cwd-keying — it likely breaks session isolation on
serve. If every session's bash runs in `process.cwd()` rather than
`/workspace/sessions/<id>/`:

- The agent operates outside its session workspace; concurrent sessions can
  read/clobber each other's files.
- Per-session `opencode.json` permissions (the `rm`/`ssh`/etc. denies in
  `opencode_config.py:_PERMISSIONS_TEMPLATE`) aren't applied per session — only
  the pod-wide `OPENCODE_CONFIG_CONTENT` permissions are.

**Verify empirically:** create two serve sessions with distinct workspaces, run
`pwd` in each; if both report the same directory, the gap is confirmed.

**Root-cause fix (separate workstream):** have the serve client send the
directory as a `?directory=` query param or `x-opencode-directory` header on
**every** request (create *and* prompt), not in the body. That restores
per-session cwd, per-session config, *and* makes cwd-keying viable as an
alternative identity key. The session-id approach in this doc does **not**
depend on that fix, so approvals can proceed regardless — but the isolation bug
should be tracked on its own.

## When this is not enough

If the threat model becomes *adversarial agent within a single user* (the agent
actively tries to misattribute its egress to a sibling session to dodge a
per-session policy), the cooperative tag is insufficient and the strict
per-session-UID + iptables-owner design in
[session-resolution-issues.md](./session-resolution-issues.md) §"Per-session
UID" is the durable answer. For the v0 goal — correct card routing under
concurrent honest sessions, including scheduled-task overlap — the session-id
hook is exact and ships without per-session infrastructure.
