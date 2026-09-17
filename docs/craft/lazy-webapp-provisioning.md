# Lazy Webapp Provisioning + `webapp` Tool

Re-derivation plan, written against current `main`. The original implementation
lives on the abandoned `no-auto-webapp` branch (forked at `346deae897`), which
predates a large refactor of the sandbox provisioning layer. This plan maps each
feature concept to where it now lives and calls out what has already landed on
main so it is not re-implemented.

## Issues to Address

- **Eager webapp provisioning is wasteful.** Every interactive session pays a
  template copy + `bun install` + a long-lived `next dev` server + a
  globally-scarce per-user port at setup, even though roughly two-thirds of
  sessions never build a web app. Make provisioning **lazy**: scaffold, install,
  and start the dev server only when a web app is actually being built.
- **The agent has no native, self-healing surface to manage the dev server.**
  Give it a `webapp` opencode tool (`start` / `status` / `logs` / `restart`)
  that returns a structured observation every call and reconciles state, instead
  of ad-hoc bash the agent has to compose and interpret.
- **The Preview tab shows a broken/empty frame before the server is up.** Gate
  the tab on actual readiness.

## Important Notes

### Already on main — do NOT re-implement

The single most important research finding: several pieces of the feature's
original scope have already merged independently. Re-implementing them would
create conflicts and drift.

- **env-baking** (already merged). `build_nextjs_start_script`
  (`sandbox/nextjs_dev.py`) already writes `.nextjs-port`, exports
  `ONYX_WEBAPP_PORT` / `ONYX_WEBAPP_BASE_PATH`, and uses a `PORT_FLAG` fallback;
  both managers set the pod/container env `ONYX_WEBAPP_ALLOWED_DEV_ORIGINS`
  (k8s ~L538, docker ~L565). So a hand-run `bun run dev` already binds the
  correct port and basePath. The lazy bootstrap must **embed main's current**
  `build_nextjs_start_script`, not the feature's older copy.
- **Per-user, interactive-gated port allocation.**
  `reserve_nextjs_port__no_commit(db_session, build_session)`
  (`db/build_session.py` ~L576) allocates per-user over `[SANDBOX_NEXTJS_PORT_START,
  SANDBOX_NEXTJS_PORT_END)`, is called only for `SessionOrigin.INTERACTIVE`
  (`session/manager.py` ~L542) and re-allocated on wake (`session/api.py` ~L427),
  persisted on `build_session.nextjs_port`. The feature's port work is done.
- **Readiness probe + info endpoint.** `_check_nextjs_ready`
  (`session/manager.py` ~L1500) GETs a basePath-scoped `_next/static` probe; the
  webapp-info endpoint already returns `has_webapp`, `webapp_url`, `ready`,
  `status`.
- **Frontend readiness polling.** `OutputPanel.tsx` already SWR-polls webapp-info
  and sets `isWebappReady` — but today that only drives polling, not tab
  visibility (see gating work below).

### Integration points in main's refactored code

- **opencode config:** `build_opencode_base_config(disabled_tools, dev_mode,
  plugins)` (`sandbox/util/opencode_config.py` ~L190) sets `config["plugin"] =
  list(plugins)`. The plugin list is assembled per-manager from
  `_OPENCODE_*_PLUGIN_PATH` constants — k8s ~L1104-1110 (unconditional), docker
  ~L844-852 (session-tag appended only when `SANDBOX_PROXY_HOST`).
- **Eager start to replace:** `build_session_workspace_setup_script(session_path,
  agents_md, session_opencode_config_json, nextjs_port)`
  (`sandbox/session_workspace.py` ~L47) interpolates
  `build_nextjs_start_script(...)` when `nextjs_port` is set (~L83-87, L132),
  after the setup `flock` closes. This is the lazy switch point.
- **Restore:** both managers' `restore_snapshot(..., nextjs_port, ...)` exec
  `build_nextjs_start_script(check_node_modules=True)` after
  `regenerate_session_config` (k8s ~L1841, docker ~L1474).
- **Setup call sites:** `setup_session_workspace` (k8s ~L1362, docker ~L1068)
  build the per-session config via `build_provider_opencode_config` then call
  `build_session_workspace_setup_script(..., nextjs_port=nextjs_port)`.

(Line numbers are hints; resolve by symbol name — the files are actively changing.)

### Settled design decisions

- **One bootstrap implementation, two callers.** The scaffold/install/start
  logic is a server-rendered `start-webapp.sh` embedded once. Both the agent
  (mid-turn) and the manager (restore auto-start) run it. It stays self-contained
  (no CLI, no backend round-trip).
- **The `webapp` tool is the ergonomic layer, not correctness-critical.** Because
  env-baking already guarantees the port/basePath, a stray `bun run dev` no
  longer breaks the preview. The tool's job is reconcile-to-running, readiness
  waiting, log tailing, restart, and structured observations — not to be the sole
  path to a working preview.
- **Tamper hardening (simplified 2026-08).** A single `start-webapp.sh` at the
  session root, `chmod 444` (rewrites unlink-then-write, since 444 blocks
  in-place overwrite). OpenCode's edit/write/patch permissions deny mutations
  to the script, and bash permissions deny commands that mention it except the
  documented `bash start-webapp.sh` fallback. No canonical/visible pair and no
  tool-side restore: if the script is otherwise deleted, the tool reports
  unavailable and setup/restore regenerates it. Liveness is guarded once,
  inside the embedded start script (pid + cwd identity); the bootstrap wrapper
  does not duplicate the check.
- **Restore auto-starts only when a webapp exists**, keyed on
  `outputs/web/package.json` in the restored snapshot. Self-heals legacy sessions
  and skips sessions that never built a webapp — no migration needed.
- **No auto-supervisor, no port auto-heal.** A crashed server stays down and
  loud so the agent reads the error and fixes its code; the managed port is the
  proxy's routing contract, so a port conflict fails with guidance rather than
  moving to another (unreachable) port.

### Portable artifacts to lift from `no-auto-webapp`

- `image/opencode-plugins/webapp.ts` — the tool. Nearly verbatim (only the plugin
  registration path is manager-side).
- `build_webapp_bootstrap_script` in `nextjs_dev.py` — adapt to embed main's
  current `build_nextjs_start_script` (drop the feature's extra `8>&-`: main's
  start script owns fd 9 itself).
- Frontend gating logic in `OutputPanel.tsx` / `PreviewTab.tsx` — re-apply on top
  of main's current polling code.

## Implementation Strategy

1. **Bootstrap generator** (`nextjs_dev.py`): add
   `build_webapp_bootstrap_script(session_path, nextjs_port)` embedding main's
   `build_nextjs_start_script(check_node_modules=True)`. flock-guarded, idempotent
   (pid-alive short-circuit), scaffolds `outputs/web` + bun-cache + install on
   first run, waits ~90s for readiness, emits plain-English recovery guidance.
2. **Lazy setup** (`session_workspace.py`): replace the eager
   `build_nextjs_start_script` interpolation with writing `start-webapp.sh` at the
   session root, `chmod 444`. No dev server started at setup. Headless (`nextjs_port is None`) path unchanged.
3. **Tool registration** (both managers): add
   `_OPENCODE_WEBAPP_PLUGIN_PATH = "/workspace/opencode-plugins/webapp.ts"` and
   include it in the base-config plugins list (k8s unconditional block; docker
   list). Ship `webapp.ts` in the image.
4. **Restore conditional-start** (both managers' `restore_snapshot`): rewrite
   `start-webapp.sh` with the re-allocated port, then auto-start via
   `start-webapp.sh` only if `outputs/web/package.json` exists (sentinel-guarded
   exec). Background the auto-start so wake stays fast (see edge below).
5. **Frontend gating** (`OutputPanel.tsx` + `PreviewTab.tsx`): drive tab
   visibility from the already-fetched `has_webapp` / `ready`. Latch
   "has-been-ready" so the tab enables once the server first serves; one-shot
   auto-switch to Preview when it becomes ready (race-guarded per session); pass
   the iframe URL only once ready; `PreviewTab` gets a "no web app yet" empty
   state.
6. **Docs** (`AGENTS.template.md` + `templates/outputs/web/AGENTS.md`): document
   the `webapp` tool as primary, `bash start-webapp.sh` as fallback.
7. **Edge — restore-time install:** the restore auto-start runs `bun install`
   synchronously (node_modules is excluded from snapshots). Background the whole
   bootstrap on restore so wake isn't blocked on a cold reinstall; the frontend
   poll brings the preview up shortly after.
8. **Edge — snapshot hygiene:** exclude `.nextjs-port` and `nextjs.pid` from the
   snapshot (they are runtime scratch, like `node_modules`) so a stale port/pid
   can't mislead the tool's liveness check after a restore that skips auto-start.

## Tests

- **Unit** (`nextjs_dev`): `build_webapp_bootstrap_script` renders a valid script
  (`bash -n`), embeds the `.nextjs-port` write + env exports, and short-circuits
  on a live pid (via the single embedded guard). The setup script writes the
  `chmod 444` script and does **not** start a dev server.
- **Integration (kind, primary backbone):** assert the lazy pre-state
  (`start-webapp.sh` present, mode 444; no running dev server; no
  `node_modules`); run the tool (and `bash start-webapp.sh`) and assert it
  scaffolds + installs + serves on the managed port through the proxy; restore a
  snapshot **with** a webapp auto-starts, restore **without** one does not
  (`package.json` signal); idempotent re-invocation is a no-op. Adapt the
  feature's `test_webapp_preview.py`, `test_snapshot_restore.py`,
  `test_bun_node_modules_dedup.py`.
- **Playwright (optional):** Preview tab disabled until ready, auto-switches once
  the agent builds a webapp.

Keep it proportionate: the kind integration test is the backbone; unit tests only
for the script-generator logic.
