# Session Resolution — In-Band Identity via opencode `shell.env`

How the egress proxy can recover the **exact** originating `BuildSession`
for a gated request, instead of guessing with the most-recent-active
heuristic. This is the concrete answer to the open question left dangling
in [session-resolution-issues.md](./session-resolution-issues.md) §"Per-session
port becomes harder", option (a): *"opencode itself setting a per-session
`HTTPS_PROXY` when it spawns skill subprocesses (unclear whether opencode
supports this)."*

It does. The mechanism is the `shell.env` plugin hook. This doc sketches
how we use it.

## TL;DR

opencode rebuilds the child-process environment on **every** shell/bash/pty
invocation and runs a plugin hook (`shell.env`) while doing so. The hook
receives the invocation's working directory. Our per-session workspace path
*is* the BuildSession id (`…/sessions/<build_session_id>/…`, see
`sandbox/base.py:85-98`). So a single global plugin can stamp the originating
session id onto each outbound request as **proxy credentials**, and the proxy
reads them to route the approval card precisely — no per-session ports, no
per-session UIDs, no `last_activity_at` race.

The session id rides in `Proxy-Authorization`, which is hop-by-hop: the proxy
consumes it and it never reaches the origin (Slack etc.), so it does not
collide with the real `Authorization` credential the proxy injects in Phase 2.

This is **cooperative** identity (userland env, not kernel-enforced), so it
does not replace the strict per-session-UID design for an adversarial-agent
threat model. It does fully solve the stated v0 problem: routing the card to
the right chat tab when an interactive session and a scheduled-task session
are active on the same sandbox at once.

## Why this beats the v0 heuristic

| | v0 heuristic (shipped) | This proposal |
|---|---|---|
| Identity source | src-IP → user → most-recent-active session | src-IP → user (anchor) **+** session id in `Proxy-Authorization` |
| Concurrent same-user sessions | races on `last_activity_at`; card may land in wrong tab | exact; each request names its own session |
| Relies on scheduled-task serialization for routing correctness | yes (`phase-1-proxy.md` T1.4 note) | no |
| Per-session infra (ports / UIDs) | none | none |
| Enforcement | n/a | cooperative (see §Trust model) |

## The opencode mechanism (verified against the opencode tree)

All citations are into the opencode repo (`anomalyco/opencode`,
`packages/opencode`).

### `shell.env` fires per command, with the cwd

`tool/shell.ts:412-422` — the bash tool builds the spawned process env fresh,
merging plugin output over `process.env`:

```ts
const shellEnv = Effect.fn("ShellTool.shellEnv")(function* (ctx, cwd) {
  const extra = yield* plugin.trigger(
    "shell.env",
    { cwd, sessionID: ctx.sessionID, callID: ctx.callID },
    { env: {} },
  )
  return { ...process.env, ...extra.env }   // hook output wins
})
```

- Called per command at `tool/shell.ts:637`, inside `execute()` which runs
  once per tool call with its own `ctx`/`cwd`.
- The merged env is handed straight to the child at `tool/shell.ts:289`
  (`ChildProcess.make(..., { cwd, env })`).
- The PTY path does the same at `pty/index.ts:196-203`.

**Concurrency is safe by construction.** `cwd`/`sessionID` are passed as
arguments per invocation and the env object is local to that spawn. Two
sessions issuing commands simultaneously each build their own env from their
own cwd. There is no shared mutable state to race — which is exactly the
property the heuristic lacks.

**Key on `cwd`, not `sessionID`.** Two reasons:
1. `cwd` is the only field present in **both** the shell and pty hook calls
   (`pty/index.ts:196` passes only `{ cwd }`).
2. `cwd` is stable across sub-agents. A `task`/sub-agent spawns a child
   opencode session with a *different* `sessionID` but the **same working
   directory**. Keying on `sessionID` would fail to map a sub-agent's egress
   back to the BuildSession; keying on `cwd` does not.

### Hook surface

`shell.env` is a documented, stable hook
(`skill/prompt/customize-opencode.md:272-287`). A plugin is an async factory
returning hook callbacks (`…:257-269`). Plugins are registered via the
`plugin` array in opencode config, which accepts an npm name **or a file
path** (`config/plugin.ts:10-13`, loader normalizes paths via
`pathToFileURL`).

## The identity key: cwd → BuildSession id

Per-session workspaces are laid out as (`sandbox/base.py:85-98`):

```
$SANDBOX_ROOT/sessions/<session_id>/
```

and `<session_id>` is the `BuildSession` UUID — `setup_session_workspace`
takes `session_id: UUID` and creates `sessions/$session_id/…`
(`sandbox/base.py:159-193`). opencode is pointed at this path as `cwd`
(`ensure_session(..., cwd=session_path)`, see
[opencode-serve-client.md](../opencode-serve-client.md) §`ensure_session`).

So the hook can recover the BuildSession id by parsing `cwd`:

```
cwd = /workspace/sessions/4f3c…-…/outputs   →  build_session_id = 4f3c…
```

This is a **direct primary-key** for `BuildSession`. No dependence on
`BuildSession.opencode_session_id`, no extra mapping table, and it survives
sub-agent child sessions.

## The carrier: `Proxy-Authorization`, not the request's `Authorization`

The plugin replaces the proxy URL's userinfo so the session id travels as
proxy basic-auth. Phase 1 already sets a static `HTTPS_PROXY`/`HTTP_PROXY`
pointing at `http://sandbox-proxy:<port>` (`phase-1-proxy.md` T1.3). The hook
rewrites it to carry credentials:

```
HTTPS_PROXY = http://<build_session_id>:<per-pod-proxy-secret>@sandbox-proxy:<port>
```

What the proxy sees:

- **HTTPS (Slack, the common case):** the agent's client issues
  `CONNECT api.slack.com:443` to the proxy carrying
  `Proxy-Authorization: Basic base64(<sid>:<secret>)`. That header is on the
  *tunnel setup*, entirely separate from the TLS-encrypted inner request. It
  never reaches Slack.
- **Plain HTTP:** `Proxy-Authorization` is a hop-by-hop header (RFC 7235); the
  proxy consumes it and does not forward it.

Either way, the session tag does **not** land on the request's own
`Authorization` header — so it composes cleanly with the Phase-2 credential
injection (proxy reads `Proxy-Authorization` to identify the session/user,
then injects the user's real `Authorization: Bearer …` into the forwarded
request). Two different headers, two different jobs:

| Header | Set by | Consumed by | Forwarded to origin? |
|---|---|---|---|
| `Proxy-Authorization` | `shell.env` plugin (session tag) | the proxy | No |
| `Authorization` | the proxy (Phase 2 cred injection) | origin (Slack) | Yes |

## Proxy-side changes (extends Phase 1 `IdentityResolver`)

`IdentityResolver.resolve()` (`sandbox_proxy/identity.py`, `phase-1-proxy.md`
T1.4) gains a header-first path. Source-IP resolution stays as the **trust
anchor**; the header only disambiguates *which session of the
already-resolved user/sandbox*.

```
resolve(src_ip, proxy_auth_user, proxy_auth_pass) -> SessionContext | None:
  1. anchor = SandboxIPLookup(src_ip)          # IP → sandbox + tenant + user  (trusted)
     if anchor is None: return None            # unidentified; Phase 2 gate rejects

  2. if proxy_auth_user parses as a UUID:
       bs = BuildSession.get(id=proxy_auth_user)
       if bs is not None
          and bs.user_id == anchor.user_id            # same user as the IP anchor
          and bs.sandbox_id == anchor.sandbox_id       # same sandbox as the IP anchor
          and (optional) constant_time_eq(proxy_auth_pass, per_pod_secret(anchor)):
            return SessionContext(session=bs, ...anchor...)   # EXACT

  3. # no/invalid header (opencode's own LLM calls, non-shell egress, tampering):
     fall back to most-recent-active heuristic over anchor.user_id   # = today's behavior
```

- Step 1 is unchanged and remains the security boundary: a sandbox cannot
  spoof its source IP, so it cannot claim another user's/sandbox's identity.
- Step 2 is the precise win. The cross-checks (`user_id`, `sandbox_id`) bound
  any header tampering to *within the same user+sandbox* — strictly no worse
  than today, and exact in the honest case.
- Step 3 keeps the system correct for traffic that legitimately carries no tag
  (see §Coverage) and preserves v0 behavior as the floor.

The `PassthroughAddon` (`phase-1-proxy.md` T1.5) and the Phase-2 `GateAddon`
read `flow.request.headers["Proxy-Authorization"]` (mitmproxy surfaces the
CONNECT auth on the flow) and pass the parsed username/password into
`resolve()`.

## Coverage — what gets an exact tag and what doesn't

| Egress source | Carries session tag? | Resolution |
|---|---|---|
| Skill/bash subprocess (`curl`, `python`, CLI) — **the gated actions** | Yes (`shell.env`) | Exact (step 2) |
| PTY / terminal | Yes (`pty/index.ts`) | Exact (step 2) |
| Sub-agent (`task`) subprocess egress | Yes — shares cwd | Exact (step 2, via cwd) |
| opencode-serve's own LLM/provider calls | No (in-process, not a shell) | IP heuristic (step 3) — acceptable; not user-cred-injected |
| opencode in-process `webfetch`/tool HTTP | No (in-process) | IP heuristic (step 3) |

The only egress that matters for approvals + credential injection is the
skill/bash class, and that is exactly what the hook covers. The in-process
classes fall back to the IP anchor, which is fine — they are not actions we
inject user credentials into.

## Trust model

- **Anchor (strong):** src-IP → sandbox → user. Kernel/informer-enforced; the
  agent cannot forge its packet source IP. This bounds everything.
- **Tag (cooperative):** the session id in `Proxy-Authorization` is a userland
  env var. A malicious or buggy process inside the sandbox could overwrite
  `HTTPS_PROXY` and substitute a *different* session id — but the cross-checks
  in step 2 confine that to the same user+sandbox. Cross-user/cross-tenant
  impersonation is impossible because the IP anchor wins.
- **Optional hardening:** include a per-pod proxy secret as the password
  component (already provisioned alongside `OPENCODE_SERVER_PASSWORD`, see
  [opencode-serve-client.md](../opencode-serve-client.md) §Decision 2) and
  verify it constant-time; or HMAC the session id with that secret. This
  detects tag forgery from a process that doesn't know the secret. It does not
  make the scheme strict (the secret lives in the same pod env the agent
  runs in) — for strict identity, see the per-session-UID design in
  [session-resolution-issues.md](./session-resolution-issues.md). This proposal
  is the precise-but-cooperative middle the "per-session port" alternative was
  reaching for, achieved in-band without port allocation or lifecycle.

## The plugin (sketch)

One global plugin, baked into the sandbox image, loaded once by the long-lived
`opencode serve`. It is stateless and keys on `cwd`, so a single instance
serves every session in the pod.

```ts
// /opt/onyx/opencode-plugins/session-proxy-tag.ts
import type { Plugin } from "@opencode-ai/plugin"

const SESSION_RE = /\/sessions\/([0-9a-f-]{36})(?:\/|$)/i
const HOST   = process.env.SANDBOX_PROXY_HOST                 // e.g. "sandbox-proxy"
const PORT   = process.env.SANDBOX_PROXY_PORT
const SECRET = process.env.SANDBOX_PROXY_TAG_SECRET ?? "x"    // per-pod; optional hardening

export default (async () => ({
  "shell.env": async ({ cwd }, output) => {
    const sid = cwd.match(SESSION_RE)?.[1]
    if (!sid || !HOST || !PORT) return            // leave the static HTTPS_PROXY untouched
    const url = `http://${sid}:${SECRET}@${HOST}:${PORT}`
    output.env.HTTP_PROXY  = output.env.HTTPS_PROXY  = url
    output.env.http_proxy  = output.env.https_proxy  = url   // lowercase variants too
    // NO_PROXY and the CA-bundle env vars are already set by firewall-init (T1.3);
    // do not clobber them here.
  },
})) satisfies Plugin
```

Notes:
- It only *adds userinfo* to the host:port that Phase 1 already configured; it
  does not invent a new proxy target, so the iptables lockdown (T1.3) still
  permits the connection.
- It deliberately does **not** touch `NO_PROXY` or the CA-bundle vars
  (`NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, …) — those are set once by
  `firewall-init.sh` and inherited via `process.env`.

## Wiring

1. **Ship the plugin file** in the sandbox image (e.g.
   `/opt/onyx/opencode-plugins/session-proxy-tag.ts`).
2. **Register it globally**, not per-session, so it loads once for the per-pod
   `opencode serve`. Add its path to the `plugin` array of the pod-level
   opencode config the entrypoint supervisor provisions. (Confirm the exact
   global-config path used by the serve entrypoint;
   `sandbox/util/opencode_config.py:build_opencode_config` writes the
   per-session `opencode.json` today — the plugin belongs at the pod/global
   layer, above per-session config, since the hook is process-global and keys
   on cwd.)
3. **Provide env:** `SANDBOX_PROXY_HOST` / `SANDBOX_PROXY_PORT` already exist
   on the sandbox container (`phase-1-proxy.md` T1.3 table); add
   `SANDBOX_PROXY_TAG_SECRET` only if adopting the hardening option.
4. **Proxy:** extend `IdentityResolver.resolve()` per §Proxy-side changes and
   have the addons pass the parsed `Proxy-Authorization` through.

## Tasks

- **TS.1** — Plugin file + image bake + global-config registration (steps 1–3
  above). Verify the serve entrypoint loads it (one-time `plugin loaded` log
  line; confirm with a temp hook that writes a sentinel env var).
- **TS.2** — `IdentityResolver` header-first path with `user_id` + `sandbox_id`
  cross-checks and heuristic fallback. Unit-test: exact match; wrong-user
  header → falls back (does not leak); malformed/absent header → falls back;
  sub-agent cwd → resolves to parent BuildSession.
- **TS.3** — Addons (`passthrough`, Phase-2 `gate`) read and forward
  `Proxy-Authorization`. Confirm mitmproxy exposes CONNECT auth on the flow for
  the HTTPS path.
- **TS.4** — (optional) per-pod tag secret generation/verification, sourced
  next to `OPENCODE_SERVER_PASSWORD`.
- **TS.5** — Integration: from inside a sandbox, two concurrent sessions each
  `curl https://api.slack.com/...`; assert the proxy logs the **correct**
  distinct `session_id` per flow (not whichever has the newer
  `last_activity_at`).

## Definition of done

- Two sessions active on one sandbox, both issuing egress: each request
  resolves to its own `BuildSession` at the proxy. Demonstrably independent of
  `last_activity_at`.
- A sub-agent (`task`) subprocess's egress resolves to the parent BuildSession
  (cwd-keyed).
- A request with a forged/foreign session id in `Proxy-Authorization` does
  **not** resolve to another user's session — it falls back to the IP anchor's
  heuristic (cross-user impossible).
- opencode's own LLM/provider egress still resolves via the IP anchor (step 3)
  and is unaffected.
- Slack credential injection (Phase 2) is unchanged: the injected
  `Authorization` header is independent of the `Proxy-Authorization` tag.

## When this is not enough

If the threat model becomes *adversarial agent within a single user* (the
agent actively tries to misattribute its own egress to a sibling session to
dodge a per-session policy), the cooperative tag is insufficient and the
strict per-session-UID + iptables-owner design in
[session-resolution-issues.md](./session-resolution-issues.md) §"Per-session
UID" is the durable answer. For the v0 goal — correct card routing under
concurrent honest sessions, including scheduled-task overlap — the hook is
exact and ships without per-session infrastructure.
