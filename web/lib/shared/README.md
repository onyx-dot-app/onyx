# @onyx-ai/shared

Platform-agnostic code shared between Onyx **web** and the future **mobile** app.

It holds four things, none of which depend on any UI framework:

| Subpath | Contents |
| --- | --- |
| `@onyx-ai/shared/tokens.css` | Design tokens as **CSS custom properties** (`--sh-*`) — for web. |
| `@onyx-ai/shared/tokens` | The same tokens as a **typed JS object** (unitless numbers) — for mobile. |
| `@onyx-ai/shared/utils` | Pure TypeScript utilities (no DOM / Node / React). |
| `@onyx-ai/shared/contracts` | Cross-platform component API contracts (React-free, generic over the platform's icon/node type). |
| `@onyx-ai/shared/types` | Common DTOs and enums. |

## The one rule: zero runtime dependencies

This package ships **no runtime `dependencies`** and is **type-system-forbidden**
from touching DOM / Node / React (its `tsconfig` uses `lib: ["ES2020"]` with no
`"DOM"` and `types: []`). That is what guarantees it can be consumed by web and
mobile without ever causing a dependency conflict.

When extending it:

- **Do not** add anything to `dependencies`, and do not add a `react` /
  `react-native` / `next` dependency or peer dependency.
- **Do not** reference `window`, `document`, `process`, `Buffer`, etc. — these
  are compile errors here, by design.
- Component contracts must stay generic over platform types (e.g.
  `ButtonContract<TIcon>`) rather than importing a UI framework's types.

## Tokens

Edit the **source** in `tokens/**/*.json` — never the generated output in
`dist/`. The build (Style Dictionary) regenerates both platform outputs:

```bash
bun run build:tokens   # tokens/*.json -> dist/tokens.css + dist/tokens.js + dist/tokens.d.ts
```

The `--sh-*` prefix namespaces these variables so they never collide with
Opal's existing `--color-*` / `--text-*`. Opal remains web's design-system
source of record for now; this token set is the future cross-platform source.

## Build

```bash
bun run build       # tokens + TypeScript (tsc) -> dist/
bun run dev         # watch src/ + tokens/ and rebuild dist/ on save (local dev)
bun run typecheck   # type-check only
bun run clean       # remove dist/
```

`dist/` is generated and git-ignored; `prepare` rebuilds it on install.

Web consumes the built `dist/`, so edits don't hot-reload until `dist/` is
rebuilt. Run `bun run dev` here (alongside web's `bun run dev`) so saves
auto-rebuild `dist/` and the web dev server refreshes.

## Consuming from web

This package is staged at `web/lib/shared`, beside Opal (`web/lib/opal`), and is
a **web workspace** package — so web's Turbopack reads it in-root (it's symlinked
into `web/node_modules/@onyx-ai/shared`, exactly like Opal) and the **full
surface** works with no extra tooling:

- web lists it in `workspaces` and depends on it via
  `"@onyx-ai/shared": "file:./lib/shared"`, and adds it to `transpilePackages`
  in `next.config.js` alongside Opal.
- **Tokens:** `globals.css` does `@import "@onyx-ai/shared/tokens.css";`.
- **Types, contracts, and runtime utilities:** imported through `@/lib/shared`.

`web/tsconfig*.json` excludes `lib/shared` from web's own compile; web resolves
the package through its built `dist` types via the `exports` map (so run
`bun run build` here — `prepare` also does it on a fresh install).

Mobile (Metro/Expo) consumes the same package — tokens via the JS object
(`@onyx-ai/shared/tokens`), plus types, contracts, and utils — by pointing a
`file:` dependency at `web/lib/shared` and adding it to Metro `watchFolders`
(with `resolver.unstable_enablePackageExports` so the subpath `exports` resolve).
Metro has no filesystem-root fence, so the package's location under `web/` is
invisible to it.

## Future: extract to a private npm package

This package and Opal are both staged under `web/lib/` and are destined to become
their own repos + a **private npm package** consumed by web, mobile, and Opal. At
that point each consumer swaps its `file:` dependency for the registry version —
no other changes needed (and mobile no longer needs the `watchFolders` entry).
