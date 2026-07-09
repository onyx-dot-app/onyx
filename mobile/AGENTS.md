# Mobile App Standards (React Native + Expo)

Source of truth for AI agents working in `mobile/` (the Onyx React Native + Expo app).
It **complements but does not inherit** `web/AGENTS.md`: the mobile app has no DOM, uses
NativeWind (not web Tailwind), expo-router, and RN primitives — so web rules about HTML/CSS,
`useSWR`, Opal components, etc. do **not** apply here. Only the cross-platform design-token
vocabulary is shared, via `@onyx-ai/shared`.

## Building UI — reuse before you build

Before hand-rolling any component or screen, **check for a matching component**:

- **Mobile already has it?** Reuse it — scan `components/ui/*`, the shell layouts
  (`components/{settings,sidebar,auth,chat}`), `@/icons/*`, and other `components/*` first.
- **Only web has it?** Web (Opal `web/lib/opal/src/`, or `web/src/refresh-components/`) is the design
  source of truth. **Don't hand-roll a divergent lookalike — STOP and ask** whether to port it
  (pixel/behaviour-exact, via the `port-web-component-to-mobile` skill) or compose existing primitives.

Mirror the web counterpart's layout/spacing/color/interaction as closely as the platform allows;
document any deliberate divergence.

## Spacing: the class number is PIXELS (not web's Tailwind step scale)

**The single biggest footgun when porting from web.** Mobile spacing classes resolve to
**pixels equal to the class number**: `px-24` = 24px, `gap-8` = 8px, `h-12` = 12px. This comes
from the shared design tokens (`web/lib/shared/tokens/size.json` `spacing-block-*`, defined in
**rem**) converted in `style-dictionary.config.mjs` (`toPx` = `rem × 16`) and emitted as the
NativeWind `spacing` scale (`@onyx-ai/shared/nativewind-theme`). RN can't use `rem`/`var()` for
dimensions, so dimensions are baked to px.

Web is different: web uses **Tailwind's default step scale**, where `p-6` = step 6 = `1.5rem`
= **24px**. Same physical scale, different naming:

| Physical size | web (Tailwind step) | mobile (px-named token) |
| ------------- | ------------------- | ----------------------- |
| 8px           | `p-2`               | `p-8`                   |
| 16px          | `p-4`               | `p-16`                  |
| 24px          | `p-6`               | `p-24`                  |

**Rules:**

- **Never copy a web spacing class number to mobile.** Translate a web Tailwind step `N`
  → mobile `N × 4` (px), or just use the px you actually want — on mobile the number _is_ px.
- Stick to the token keys that exist on the scale (`0,2,4,6,8,10,12,16,20,24,28,32,36,40,44,48,…`).
  A non-token key (e.g. `p-3`) falls through to Tailwind's default rem scale — avoid it.
- **Centralize recurring spacing in a layout primitive; don't repeat it per screen.** Screen
  gutters live in shells: `components/auth/AuthScreenShell.tsx`, `components/chat/ChatScreen.tsx`
  (`CenteredContent` owns the centered screen gutter). A new screen/empty-state composes an
  existing shell instead of hardcoding `px-24`.

## Text, inputs, icons, colors

- Render **all** text via `@/components/ui/text` `Text` (`font`/`color` string-enum props). Never
  use React Native's `Text` (including in tests). `react-native` `TextInput` is unrelated and fine,
  but prefer `@/components/ui/text-input` for fields.
- Icons are default-exported from `@/icons/*`, rendered via `@/components/ui/icon` `Icon`
  (`<Icon as={SvgFoo} size={…} className="text-text-…" />`).
- Colors: use Onyx semantic classes (`bg-background-*`, `text-text-*`, `border-border-*`). They
  resolve at runtime through the `vars()` provider in `app/_layout.tsx` (light/dark from
  `@onyx-ai/shared/native`). **No `dark:` modifier; no raw Tailwind colors.**

## HTTP, data, navigation

- HTTP: `@/api/client` `apiFetch<T>` (injects bearer, normalizes errors to `ApiError`).
  `getBaseUrl()` **already appends the `/api` prefix**, so paths are bare: `apiFetch("/chat/...")`,
  `apiFetch("/me")`. The streaming chat call is the one exception (uses `expo/fetch` for a readable
  body) — see `docs/mobile-chat`.
- Server state: TanStack Query, **keyed by `serverUrl`** (`@/api/query-keys`) so switching instances
  never serves a prior backend's data. The cache persists to **unencrypted MMKV** — any PII key
  (chat content, identity) **must** be excluded via `NON_PERSISTED_KEY_PREFIXES` in `@/query/client.ts`.
- Navigation: expo-router. Route **groups are path-transparent** (`app/(app)/index.tsx` = `/`). Auth
  routing is imperative in `components/auth/AuthGate.tsx` (pure logic in `authRoute.ts`). The nav
  surface is a **foldable sidebar overlay** (Portal-based, `components/sidebar`), not a tab bar. Use
  `useGlobalSearchParams` in layouts, `useLocalSearchParams` in screens.

## Tests

- Runner: `jest-expo`. Tests live in `__tests__/` (`src/**/__tests__/**/*.test.ts?(x)`). Gate with
  `bun run typecheck`, `bun run lint`, `bunx jest`.
- **Import jest globals from `@jest/globals`** (`describe/it/expect/jest/beforeEach`) — the TS config
  carries no ambient test types. Put all imports first, then `jest.mock(...)` (babel hoists the mock;
  this also satisfies `import/first`).
- Native mocks are centralized: MMKV self-mocks, `expo-secure-store` manual mock in `__mocks__/`,
  resets in `jest.setup.ts`.
- A generic fn like `apiFetch<T>` makes `jest.mocked()` infer `never` — cast it:
  `apiFetch as unknown as Mock<(p: string, i?: ApiFetchInit) => Promise<unknown>>` (`Mock` from `jest-mock`).
- **Don't import reanimated-pulling barrels in unit tests.** `@/components/sidebar` (→ `Sidebar.tsx`
  → reanimated) crashes under jest ("Worklets not initialized"). Import leaf components directly
  (e.g. `@/components/sidebar/SidebarTab`) to keep a component unit-testable.

## Shared package (`@onyx-ai/shared`)

- Holds cross-platform **design tokens** + neutral **contracts/types/utils**. `@onyx-ai/shared/native`
  is **RN-only** (NativeWind theme/vars/typography); cross-platform types go in `/contracts`, never `/native`.
- Grow it **extract-on-proven-reuse**, not upfront. The mobile **chat** layer is written natively in
  `mobile/src/chat/` (NOT shared) by decision — see `docs/mobile-chat/05-pr-roadmap.md` (PR 2 Decision).
- Editing the shared package requires rebuilding its `dist` (`bun run build` in `web/lib/shared`); the
  mobile `file:` dep consumes `dist`. Web jest resolves it from `src` via a `moduleNameMapper`.
