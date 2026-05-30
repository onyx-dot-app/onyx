# Onyx Mobile (Expo)

React Native mobile app for Onyx. Lives inside the `onyx` monorepo as the `mobile` Bun
workspace. Design: `docs/plans/2026-05-30-mobile-app/` (start with `overview.md`).

> **Status: foundation only (Phase 0, doc 01).** This is the workspace + resolution plumbing.
> The app shell here is the stock Expo Router template — the real route tree, UI, state, and
> networking land in later phases. Most things below are intentional stubs.

## Stack (locked)

- **Expo SDK 56** (managed, New Architecture) · **Expo Router** · React 19.2 / RN 0.85.
- **NativeWind v4** + Opal design tokens (doc 03 / 05) — _not wired yet_.
- Zustand + TanStack Query (doc 06); `expo/fetch` NDJSON streaming + PAT auth (doc 07).
- Shared code in `../packages/{api-types,api-client,design-tokens}` (`@onyx-ai/*`).

## First-time setup

The monorepo is not installed yet. From the **repo root** (`onyx/`):

```bash
bun install             # installs all workspaces into one hoisted tree (root bun.lock)
cd mobile && bunx expo install --fix  # pin native deps to the SDK if needed
```

> Node LTS must be on PATH for `expo prebuild` / CNG even though Bun runs the app.
> Native builds use **cloud EAS** (Bun is unsupported for local EAS builds).

## Run

```bash
cd mobile
bun run ios        # or: bun run android / bun run web
```

## Monorepo notes

- `metro.config.js` watches the repo root so edits in `../packages/*` hot-reload.
- `@onyx-ai/*` packages are **source-only** (no build step) — resolved via the workspace
  symlink + each package's `package.json` `"types"`/`"main"` → `src/index.ts`.
- `tsconfig.json` extends both `expo/tsconfig.base` and the shared `../tsconfig.base.json`.
