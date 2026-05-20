# Sandbox node_modules dedup via Bun

## Context

Each Craft session in a sandbox currently runs `npm install` against the
Next.js template in `outputs/web/`. Measured cost per session on the
`onyxdotapp/sandbox:v0.1.44` image:

| | Per session |
|---|---|
| node_modules size on disk | ~836 MB |
| `npm install` wall time | ~30 s |
| node_modules file count | ~48,700 |

The user-shared sandbox model means one Docker named volume (or one K8s
emptyDir) holds N session workspaces. Disk usage scales linearly with N:

| Sessions per sandbox | Volume size |
|---|---|
| 1 | ~715 MB |
| 5 | ~3.5 GB |
| 10 | ~7 GB |

This is fine on K8s (emptyDir is ephemeral, cluster has space) but bites on
docker-compose deployments where the host is typically a single small EC2.
It's also wasted I/O: ~95% of the time the lockfile is identical across
sessions, so we're reinstalling the same tree.

## Issues to Address

1. node_modules duplicated across every session in a sandbox.
2. ~30 s of cold-start latency per session, dominated by `npm install`.
3. Agent-driven `npm install <new-pkg>` mid-session must continue to work
   and must not corrupt other sessions in the same sandbox.

## Important Notes

- Container images live on a shared registry; image size affects pull time
  on every CI run and on every new EC2. Baking node_modules into the image
  would add ~836 MB to a 675 MB image — meaningful penalty.
- The Next.js template (`backend/onyx/server/features/build/sandbox/kubernetes/docker/templates/outputs/web/`)
  is shared by all session, and the `package.json` / lockfile in there is
  the canonical version. Sessions never diverge from this lockfile unless
  the agent explicitly modifies `package.json`.
- The hot path is "session sets up → preview is reachable in under a few
  seconds." Long npm-install wait blocks user-visible UX on every new
  session.

## Decision: Bun + Bun workspaces

We replace `npm install` with `bun install` and structure
`/workspace/sessions/` as a Bun workspace root. Key properties:

- **Content-addressable global install cache**: Bun keeps tarballs in
  `~/.bun/install/cache` and uses **hard-links** by default when populating
  a project's `node_modules` (configurable via `--backend=hardlink`, which
  is the default on Linux). So per-session disk overhead drops to inode
  metadata — effectively zero.
- **Workspace mode**: a top-level `package.json` at `/workspace/sessions/`
  with `"workspaces": ["*/outputs/web"]` makes Bun resolve once, share a
  single global node_modules under `/workspace/sessions/node_modules/`,
  and *also* maintain per-session `node_modules/.bin` shadows. Sessions
  read their deps from the hoisted store via the workspace resolution
  algorithm.
- **Speed**: `bun install` is typically 10–25× faster than `npm install`.
  Cold session setup should drop from ~30 s to ~2–5 s.

## Architecture

```
/workspace/sessions/
├── package.json          # workspace root (baked into image OR written at provision)
├── bun.lock              # shared lockfile (baked into image)
├── node_modules/         # ONE hoisted tree per sandbox (Bun-managed)
│   └── <flat deps>
├── .shared/
│   └── ... (already-used for snapshot bootstraps if any)
└── <session_id>/
    └── outputs/
        └── web/
            ├── package.json        # workspace member, references hoisted deps
            └── node_modules/       # workspace-local symlinks/.bin entries
```

The setup script becomes:

1. Copy template into `session/outputs/web/`.
2. Ensure the workspace's `node_modules/` is populated. On first session,
   `bun install --frozen-lockfile` at the workspace root. Subsequent
   sessions: no-op (the hoisted tree is already there).
3. Bun's `postinstall` ensures workspace members have their resolution
   wired up.

### Agent runs `bun install <new-pkg>` mid-session

Bun's workspace install will add `<new-pkg>` to the *member's*
`package.json` and the hoisted root `node_modules`. Other sessions in the
same sandbox would see the new package's resolution but **wouldn't import
it** (it's not in their `package.json`). The only risk is if the new
package's version *upgrades* a transitive shared with another session's
expectations; Bun handles this via the hoisted-vs-nested fallback in the
workspace algorithm.

If full isolation per session is required after all, we fall back to one
of two patterns:
1. Run `bun install` with `--no-save --linker=isolated` inside the
   member (Bun supports an isolated-installs mode that mirrors pnpm's
   per-project store). Each session gets its own dep tree backed by the
   global cache.
2. Keep workspaces off; do a normal `bun install` per session. Bun's
   hardlink backend still gives us O(file count) inodes but ~0 disk per
   session because all files are hardlinked from the global cache. This
   is the simplest fallback and likely "good enough" without workspaces.

## Implementation Strategy

### PR A — Sandbox image switches from npm to bun

- Update `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile`:
  - Install Bun (`curl -fsSL https://bun.sh/install | bash`).
  - In the same RUN that copies the template, run `bun install --frozen-lockfile`
    in the template's `outputs/web/` to populate Bun's cache. The cache is
    ~50 MB of compressed tarballs (vs. ~836 MB of extracted node_modules)
    so image growth is bounded.
  - Bake `bun.lock` into the template.
- Update both K8s and Docker manager setup scripts:
  - Replace `cd outputs/web && npm install` with `cd outputs/web && bun install --frozen-lockfile`
    (or, with workspaces, run once at the workspace root).
- Update `_build_nextjs_start_script` so `dev` runs via `bun run dev`
  (Bun runs Next.js fine; only the package-manager call changes).

### PR B — Workspace hoisting (if disk savings from PR A are insufficient)

- Add a top-level `package.json` at `/workspace/sessions/` defining `*/outputs/web`
  as workspace members.
- Modify setup script to write this top-level `package.json` at provision
  time, then run `bun install` at the workspace root instead of per session.
- Add lockfile-hash check: if the session's `package-lock.json` matches the
  template's, skip per-session install entirely; if not, fall back to
  isolated install just for that session.

### PR C — Image-level dedup of Python venv

Same problem exists for `/workspace/.venv` if sessions ever start mutating
deps. Out of scope for this plan but worth tracking.

## Tests

- **External-dependency-unit**: spin up the new sandbox image against real
  Docker; setup 3 sessions; assert:
  - `du -sh /workspace/sessions/` is well under 1 GB.
  - Each session can run `bun run dev` and serve the Next.js preview.
  - Agent-driven `bun install lodash` in session A doesn't break session B.
- **Benchmark**: time `setup_session_workspace` cold (first session) and
  warm (2nd+ session in same sandbox). Target: < 5 s warm.
- **Image size**: assert the new image is within ~100 MB of the current
  image (allowed growth for Bun binary + Bun cache).

## Open Questions

1. Does Bun's `--linker=isolated` actually exist and work for our deps?
   Bun has been moving fast in this space — needs verification before
   committing to the workspace approach.
2. Does Next.js dev mode have any sharp edges when started via `bun run dev`
   vs `npm run dev`? Likely fine but worth confirming with the template's
   exact version of Next.js (16.x).
3. Do any of our template's deps have postinstall scripts that assume
   `npm` specifically? We can audit via `grep -r postinstall package.json`
   in the template.
4. K8s parity: do we ship this only for Docker, or also flip K8s? The
   per-session emptyDir cost is wasted I/O regardless; flipping K8s would
   benefit cloud users too. Recommend: flip both, since the image is
   shared.

## Non-Goals

- Switching the entire codebase to Bun — only the sandbox image.
- Replacing Python venv setup. That's a separate workstream.
- Backwards compatibility for sandbox image versions older than the bun
  cutover. Forward-only.
