# Browser use

Give the Craft **agent** a real browser it can drive for tasks `webfetch` can't
do — JS-rendered pages, clicking, forms, multi-step flows, screenshots, scraping,
logging into sites, and visually checking the app it's building.

This is **agent-only**: the browser is headless and the user does not see or
drive it. The webapp preview is unchanged (it remains the normal webapp preview).
There is no streamed browser, no human takeover, and no open-internet streaming.

## How it works

The agent drives a real Chromium (via [`vercel-labs/agent-browser`](https://github.com/vercel-labs/agent-browser),
a Rust daemon + CLI over CDP) from its `bash` tool. It works the accessibility
tree: `browser open <url>`, `browser snapshot -i` (compact `@eN` refs), then
`browser click/type` those refs — ~200–400 tokens per step instead of raw HTML.

### The `browser` command (`image/browser-cli.sh` → `/usr/local/bin/browser`)

A thin wrapper over `agent-browser`, baked into the sandbox image, that makes the
agent's life simple — it just uses the plain commands. The wrapper, per call:

- **Pins the session** — injects `--session <uuid>` resolved from the cwd
  (`/workspace/sessions/<uuid>/`), so each session drives its own browser. One
  pod hosts many sessions, so this can't be a global env; the cwd is the only
  reliable per-call signal. Skipped if the caller already passed
  `--session`/`--auto-connect`/`--cdp`.
- **Carries the Chromium env** — the invoking command launches Chromium when a
  session has none, so it must carry `--no-sandbox` (the pod drops caps +
  seccomp), the egress proxy as a `--proxy-server` flag (Chromium ignores
  `*_PROXY` env; userinfo is stripped since the proxy authorizes by source IP),
  and headless-stability flags. Defaults only — anything already exported wins.

Proxy-CA trust is **not** done here — it's a once-at-startup step in
`entrypoint.sh` (the main container, as uid 1000), which imports the egress-proxy
CA bundle into Chromium's per-user NSS db (`~/.pki/nssdb`) so HTTPS through the
MITM proxy is trusted. It runs in the main container (not the K8s
`firewall-init` initContainer, whose `/home/sandbox` isn't shared), splits the
bundle and imports every cert (`certutil -A -i` imports only the first), and is
a no-op without the browser runtime.

Why a real PATH executable and not a bashrc alias: opencode runs the agent's
`bash` tool in non-interactive shells, which don't source `~/.bashrc` or expand
aliases.

### The `browser` built-in skill

`backend/onyx/skills/builtin/browser/SKILL.md` is `agent-browser`'s own core
usage guide (pulled from `agent-browser skills get core --full`, version-matched
to the pinned CLI) with every `agent-browser` rewritten to `browser`, the install
lines dropped (pre-installed), and a short Onyx note (headless; pinned session;
no `--session`). It's a normal seeded built-in skill:

- Registered in `onyx/skills/built_in.py` with `is_available` keyed on
  `ENABLE_BROWSER`.
- Row seeded by migration `c4e7b1a9f2d3_seed_browser_built_in_skill`.
- **Gated per-deployment**, not per-user: the registry's `is_available` returns
  `ENABLE_BROWSER`, so `_exclude_unavailable_built_ins` hides the skill from
  sandbox injection wherever the image was built without the browser runtime. No
  PostHog flag — like `pptx`/`company-search`, it's a plain built-in skill; the
  only question is whether the image has the `browser` command, which is a
  deployment property, not a per-user one.

The agent discovers and uses it like any other built-in skill — it appears in the
AGENTS.md skills list with its description, and the agent reads its `SKILL.md`.
No dedicated AGENTS.md section is needed.

## Gating

`ENABLE_BROWSER` (`onyx/server/features/build/configs.py`, api-server runtime
env, default ON): must match the sandbox image's build-time `ENABLE_BROWSER` ARG
(also default ON). It's the single signal of "does this deployment's image
include the browser runtime," and gates the built-in `browser` skill via the
registry. There is no per-user feature flag. Both defaults are on, so the
standard released image surfaces the skill; a deployment that builds a
browserless sandbox (`--build-arg ENABLE_BROWSER=false`) must also set this
runtime env `false`, or the skill is advertised without its runtime.

## Image

`image/Dockerfile`, gated on `ENABLE_BROWSER=true` (default; set false in dev/CI
to skip ~400 MB): installs `chromium` (system, arm64-native — we point the daemon
at it via `AGENT_BROWSER_EXECUTABLE_PATH` rather than `agent-browser install`,
which fetches a no-arm64 Chrome-for-Testing) + `libnss3-tools` (certutil) +
`agent-browser` (npm global). The `browser` wrapper is always copied; it's inert
when `ENABLE_BROWSER=false` (agent-browser absent) and only advertised via the
deployment-gated skill.

## Browser state is ephemeral

agent-browser keeps per-session state (cookies, localStorage, the Chromium
profile) under a fixed `~/.agent-browser/` (= `/home/sandbox/.agent-browser/`,
outside the snapshotted `/workspace/sessions/<id>` volume). The wrapper passes
neither `--profile` nor `--restore`, so browser state is intentionally ephemeral
— it lives only for the daemon's lifetime and is **not** captured by session
snapshots; logins/cookies do not survive a pod reap or restore.

Making it persist would mean relocating agent-browser's data dir under
`/workspace` (no data-dir env override exists beyond `AGENT_BROWSER_SOCKET_DIR`;
the lever is `HOME`) and using `--restore` (cookies+localStorage only, not a full
`--profile`) — which writes auth cookies into the S3 snapshot. That's a
deliberate security/size tradeoff to revisit only if a "resume a logged-in
browser across reaps" use case appears.

## Not in scope

- No screencast / streamed browser to the frontend.
- No human-driven browser or pixel-input takeover.
- No socat forwarder, stream ports (8930/8931), WS proxy, or `/browser-input`
  endpoint — the agent uses snapshot/click (CDP), which don't need the screencast.
- The webapp preview is untouched.
