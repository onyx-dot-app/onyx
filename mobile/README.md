# Onyx Mobile (Expo)

A **standalone** React Native app for Onyx. It lives in the `onyx` repo under `mobile/` but is
fully independent of `web/` — its own dependencies, lockfile, and tooling, so web and mobile
scale separately. Design docs: `docs/plans/2026-05-30-mobile-app/` (start with `overview.md`).

> **Status: foundation (Phase 0).** The app shell is a trimmed Expo Router starter; the real
> route tree, UI, state, and chat networking land in later phases. `src/lib/api/` holds the API
> client (ported from web, mobile-owned).

## Stack

- **Expo SDK 56** (managed, New Architecture) · **Expo Router** · React 19.2 / RN 0.85.
- **NativeWind v4** + Opal-derived design tokens (doc 03 / 05) — _not wired yet_.
- Zustand + TanStack Query (doc 06); `expo/fetch` NDJSON streaming + PAT auth (doc 07).

## First-time setup

This is a standalone app — install from **inside `mobile/`**:

```bash
cd mobile
bun install              # creates mobile/bun.lock + mobile/node_modules
bunx expo install --fix  # pin native deps to the SDK if needed
```

> Node LTS must be on PATH for `expo prebuild` / CNG even though Bun runs the app.
> Native builds use **cloud EAS** (Bun is unsupported for local EAS builds).

## Run

```bash
bun run ios        # or: bun run android / bun run web
```

## Notes

- `src/lib/api/` — the API client (fetcher, endpoint registry, NDJSON streaming reader). Ported
  from web and de-Next-ified; mobile owns it independently.
- `metro.config.js` is the default Expo config (NativeWind's `withNativeWind` is added in doc 05).
- `bunfig.toml` pins `nodeLinker = "hoisted"` for reliable Expo + Bun + Metro resolution.
