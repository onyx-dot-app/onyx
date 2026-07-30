# @onyx-ai/shared

Platform-agnostic code shared between Onyx **web** and the future **mobile** app.

It holds four things, none of which depend on any UI framework:

| Subpath | Contents |
| --- | --- |
| `@onyx-ai/shared/tokens.css` | Design tokens as **CSS custom properties** (exact Opal names: `--text-05`, `--radius-12`, …), with `:root` (primitives + light) and `.dark` (dark overrides) — for web/Opal. |
| `@onyx-ai/shared/typography.css` | Typography **presets** as Tailwind `@utility font-*` blocks (`font-heading-h1`, `font-main-ui-body`, …) — for web/Opal. |
| `@onyx-ai/shared/nativewind-theme` | A NativeWind/Tailwind `theme.extend` fragment (semantic colors as `var(--name)`; radius/spacing as px numbers) — for mobile's `tailwind.config.js`. |
| `@onyx-ai/shared/nativewind-typography` | A `.font-*` → RN-text-style map registered as NativeWind utilities (via a tailwindcss `plugin` in mobile's `tailwind.config.js`) — the RN counterpart of web's `typography.css` `@utility font-*` blocks, so mobile can use `font-heading-h1` like web. |
| `@onyx-ai/shared/native` | `{ varsLight, varsDark, textPresets }` — resolved light/dark CSS-variable maps for the mobile NativeWind `vars()` provider (the RN analog of web's `.dark` class), plus the typography presets as RN style objects. **RN-only runtime** — shared cross-platform types live in `/contracts` (e.g. `TextFont`, `TextColor`), not here. |
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
- A contract that needs no platform value stays plain (e.g. `InteractiveContract`
  in `contracts/interactive.ts`); one that carries a platform value (an icon, a
  node) must stay generic over it — a type parameter the consumer supplies (web →
  a React component, mobile → an RN component) — rather than importing a UI
  framework's type.

## Tokens

This package is the **single source of truth for Onyx's design tokens** (colors,
spacing, radius, padding, weights, backdrop-blur, and typography metrics + font
families + presets). Opal consumes them via `@import "@onyx-ai/shared/tokens.css"` and
defines no design-token values of its own; mobile consumes the NativeWind fragment +
the `vars()` maps. (Web-app-only concerns — modal/sidebar/page widths, image heights
in Opal's `sizes.css`, and overlay stacking values in `z-index.css` — remain in Opal;
they are not cross-platform design tokens.)

Edit the **source** in `tokens/*.json` — never the generated output in `dist/`.
Token sources use the legacy `{ name, value, type }` shape; each token's key is the
**exact** CSS variable name (no prefix). Semantic colors reference primitives
(`"{alpha-grey-100-90}"`), which the build emits as `var(--alpha-grey-100-90)` so
dark mode flips at runtime exactly as before. The build (Style Dictionary)
regenerates every platform output:

```bash
bun run build:tokens   # tokens/*.json -> tokens.css + typography.css + nativewind-theme.cjs + nativewind-typography.cjs + native.js (+ .d.ts)
```

Typography presets live in `tokens/typography-presets.json` (each preset bundles
font-family, size, weight, line-height, letter-spacing). The build emits them as web
`@utility font-*` blocks (`typography.css`), as mobile `.font-*` NativeWind utilities
(`nativewind-typography.cjs`), **and** as resolved RN style objects (`textPresets` in
`native.js`) — one source, every platform. The preset names are also the `TextFont`
union in `src/contracts/typography.ts` (a neutral, both-platform type).

### No-regression gate

`bun run verify:tokens` proves the move is loss-less: it resolves every token
variable (light **and** dark) from the new output and from Opal's pre-migration CSS
on the PR **base branch** (`origin/main`, override with `PARITY_BASELINE_REF`), and
fails on any name-set or resolved-value difference. Run it while the migration PR is
open; once merged — when the baseline no longer exists on the base branch either — it
skips cleanly. A missing/unfetched ref fails loudly rather than silently skipping.

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

Mobile (Metro/Expo) consumes the same package — tokens via the NativeWind theme
fragment (`@onyx-ai/shared/nativewind-theme`, wired into `tailwind.config.js`) and
the light/dark `vars()` maps (`@onyx-ai/shared/native`), plus types, contracts, and
utils — by pointing a `file:` dependency at `web/lib/shared` and adding it to Metro
`watchFolders` (with `resolver.unstable_enablePackageExports` so the subpath
`exports` resolve). Metro has no filesystem-root fence, so the package's location
under `web/` is invisible to it. Because RN cannot use CSS variables for theming,
the semantic class (`bg-background-neutral-01`) maps to `var(--…)` and the active
palette is supplied at the app root by a `vars()` provider that swaps `varsLight` /
`varsDark` on color-scheme change — the RN analog of web's `.dark` class.

## Future: extract to a private npm package

This package and Opal are both staged under `web/lib/` and are destined to become
their own repos + a **private npm package** consumed by web, mobile, and Opal. At
that point each consumer swaps its `file:` dependency for the registry version —
no other changes needed (and mobile no longer needs the `watchFolders` entry).
