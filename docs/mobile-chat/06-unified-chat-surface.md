> Status: implemented + adversarial-reviewed (2 real regressions fixed) — local gate green (typecheck · lint · 198 jest); **on-device visual gate pending** · Task: mobile-chat · Phase: `unify-chat-input` (post-PR 6 refactor)

> **Adversarial review (2026-07-06):** 5 dimension reviewers + 2 skeptics/finding. Two real, refactor-introduced regressions found and FIXED: (1) unsent composer draft leaked across conversations via the shared persistent `useChatController` — now cleared on `[sessionId, projectId]` change; (2) cold-open of an existing chat flashed the welcome/empty state through the new cross-fade — empty branch now gated on `!isHydrating`. A third finding (body not keyed by `sessionId`) was adjudicated **not a code regression** (`MessageList` unchanged, reuse pre-existed, scroll-reset already deferred to the on-device gate) — corrected the spec prose instead. The chat↔chat draft-persist case was refuted as pre-existing (same `chat/[id]` route reused before too).

# Mobile Chat — Unified Chat Surface (single persistent screen)

## Problem

After PR 6 (projects), the chat **input and chrome are forked across two components**:

- `components/chat/ChatConversation.tsx` renders the chrome via `components/chat/ChatScreen.tsx`
  (`SafeAreaView` + `ChatHeader` + `KeyboardStickyView` + `InputBar`), used by `/` and `/chat/[id]`.
- `components/chat/ProjectView.tsx` **hand-re-implements that same chrome inline** (`ProjectView.tsx:47‑85`)
  instead of reusing `ChatScreen`, used by `/projects/[id]`.

Consequences:

1. The composer (`InputBar`) and its wiring (`value/onChangeText/onSend/onStop/chatState`) are written
   **twice** and will drift.
2. **One conversation is rendered by two different code paths** — sending inside a project keeps you on
   `/projects/[id]` (ProjectView's in-place `activeSessionId` swap), but reopening that same chat from the
   sidebar lands on `/chat/[id]` (ChatScreen). Two shells for the same thing.

## Requirement (owner, locked)

Every mode change must feel like **the same screen with its content morphing** — **not** a navigation to a
next screen:

- **empty chat → chat with a message** (first send from the landing)
- **project home → chat** (first send inside a project)
- **populated chat → empty/new chat** (the "new chat" action)
- (implied) **switching between two conversations**

Plus: **tapping the input lifts the composer above the keyboard** (already true — `ChatScreen.tsx:21`
`KeyboardStickyView`; preserved).

This supersedes the earlier "navigate to `/chat/[id]` (web-parity)" call from the design discussion: we
still change the URL (for deep-links + back-stack), but because the surface never unmounts it **reads as
in-place**, not a swap. Best of both.

## Decision & evidence

**Adopt a single persistent `ChatSurface` mounted in `(app)/_layout.tsx`**, a sibling to `<Stack>`, driven
by a **focus** derived from the route. Every transition is a `router` navigation that changes the focus; the
surface **re-renders and morphs in place — it does not remount**.

This is the same mechanism `AppSidebar` already relies on in production: it is a sibling to `<Stack>` in
`(app)/_layout.tsx` and survives every screen change. It also mirrors web's `AppPage`, which never remounts
across new/chat/project — the URL change is just an `appFocus` flip.

**Spike (headless, `expo-router/testing-library` `renderRouter`) — PASS.** Because "mount vs re-render" is
pure React reconciliation, jest models it faithfully. Verified:

| Driven | Result |
| --- | --- |
| `/` → `/chat/[id]` → `/projects/[id]` → `router.back()`, surface in `_layout` | Surface **never remounted** (mount count constant) yet **re-rendered to the new focus** each hop; back-stack worked |
| `router.setParams({chatId})` on one route | Screen **did not remount**; focus flipped in place |

The one thing jest cannot prove is visual (morph smoothness, keyboard-lift, no flash) — deferred to the
on-device gate (below).

## How it works (as implemented)

**Realization chosen: the surface is an absolute-fill overlay _above_ `<Stack>` that renders `null` on
non-chat routes** — not transparent Stack screens. This resolves grill Q1 without depending on
react-native-screens transparency/touch behavior: it's the same overlay model `AppSidebar` already uses.

```
(app)/_layout.tsx  →  <View flex-1>
  ┌─────────────────────────────────────────────────────────────┐
  │  <Stack/>         ← drives URL + back-stack. Chat routes     │
  │    (index, chat/[id], projects/[id]) render null (URL only). │
  │    Real destinations (agents) render normally, opaque.       │
  ├─────────────────────────────────────────────────────────────┤
  │  <ChatSurface/>   ← absolute overlay ON TOP of the Stack.    │
  │    focus = deriveFocus(usePathname())                        │
  │    · focus null (agents) → renders null, Stack shows through │
  │    · focus set → StyleSheet.absoluteFill overlay:            │
  │        ChatSurfaceContent stays mounted across new↔chat↔     │
  │        project (focus never null there) → header + composer  │
  │        persist; body/aux cross-fade (reanimated)             │
  ├─────────────────────────────────────────────────────────────┤
  │  <AppSidebar/>    ← unchanged; Portal → above the overlay    │
  └─────────────────────────────────────────────────────────────┘
```

A navigation (`router.replace('/chat/x')` from the landing, `router.navigate('/chat/x')` from a project,
`router.navigate('/projects/7')`, `router.replace('/')`) changes the URL → `ChatSurface` re-derives focus →
`ChatSurfaceContent` gets a new `focus` prop **without remounting**, so the header + composer stay put and only
the body/aux regions animate. Because the overlay is opaque and covers the (null) Stack chat screens, there is
nothing behind it to flash. `useChatController` is **unchanged** — the caller simply omits `onSessionCreated`,
taking the hook's existing `projectId != null ? navigate : replace` branch.

Trade-off of the overlay: the iOS edge-swipe-back gesture is covered while a chat route is active (back is via
header/sidebar instead) — acceptable and matching web, which has no swipe-back.

## Focus model

A pure function `chat/chatFocus.ts` maps the route to a focus (testable, no native deps):

```ts
type ChatFocus =
  | { kind: "new";     sessionId: null;   projectId: null }
  | { kind: "chat";    sessionId: string; projectId: null }
  | { kind: "project"; sessionId: null;   projectId: number };

deriveFocus(pathname): ChatFocus | null   // null → non-chat route (surface renders nothing)
```

Implemented over `usePathname()` (single source, race-free vs. splitting across segments + params): `"/"` →
`new`; `"/chat/<id>"` → `chat`; `"/projects/<n>"` → `project` (non-numeric / empty id → `null`); anything else
(`/agents`, …) → `null`.

| Route | pathname | focus.kind | Surface content (above / below) |
| --- | --- | --- | --- |
| `/` | `/` | `new` | empty-state (`ChatEmptyState`) / — |
| `/chat/[id]` | `/chat/<id>` | `chat` | `MessageList` / — |
| `/projects/[id]` | `projects` | `project` | `ProjectContextPanel` / `ProjectChatSessionList` |

(The derivation reuses exactly the `useSegments()` + `useGlobalSearchParams()` disambiguation already in
`AppSidebar.tsx:22‑29`.)

## The four morphs

The **chrome (`ChatHeader`) and the composer (`InputBar`) are one persistent instance** across all of these;
only the body/aux regions animate.

| Transition | Trigger | Persists | Animates |
| --- | --- | --- | --- |
| empty → chat | first send from `/` → `router.replace('/chat/x')` | header, composer | empty-state fades out, `MessageList` fades in (optimistic user bubble already seeded in the store) |
| project → chat | first send in `/projects/[id]` → `router.navigate('/chat/x')` | header, composer | context panel + session-list fade out, `MessageList` fades in, composer slides to bottom (`LinearTransition`) |
| populated → new | "new chat" → `router.replace('/')` | header, composer | `MessageList` fades out, empty-state fades in |
| chat A → chat B | sidebar select → `router.navigate('/chat/b')` | header, composer | `MessageList` data swaps in place (unsent draft is cleared) |

## Detailed design

### New

- **`mobile/src/chat/chatFocus.ts`** — `deriveFocus(segments, params) → ChatFocus` (pure). Unit-tested.
- **`mobile/src/components/chat/ChatSurface.tsx`** — the persistent host. Derives focus, calls **one**
  `useChatController`, renders the slotted shell, owns the morph animations. This is the merge target for
  `ChatConversation` + `ProjectView`.

### Changed

- **`mobile/src/components/chat/ChatScreen.tsx`** — evolve into the slotted shell: add an optional
  **`below?: ReactNode`** slot (rendered as a sibling after the `KeyboardStickyView`), used only by project
  focus. `above` = `children`, `composer` = `input` (unchanged). `CenteredContent` stays.
- **`mobile/src/app/(app)/_layout.tsx`** — mount `<ChatSurface/>` as a sibling to `<Stack>` (alongside
  `<AppSidebar/>`). Configure the surface-backed routes (`index`, `chat/[id]`, `projects/[id]`) as
  transparent/`animation:"none"` so the surface shows through without a swap; leave real destinations
  (`agents`, future settings) as normal screens.
- **`mobile/src/app/(app)/index.tsx`**, **`chat/[id].tsx`**, **`projects/[id].tsx`** — collapse to null
  focus-reporter screens (they exist only for the URL + back-stack; the surface renders the content). The
  param parsing that used to live in `projects/[id].tsx` moves into `deriveFocus`.
- **`mobile/src/hooks/useChatController.ts`** — **logic unchanged.** Only the *caller* changes: `ChatSurface`
  stops passing `onSessionCreated`, so the controller takes its existing default branch
  (`projectId != null ? router.navigate : router.replace`, `useChatController.ts:274‑287`). That single branch
  already gives us: project first-send → push (back returns to project), landing first-send → replace (back
  skips the empty landing). No new controller code.

### Deleted

- **`mobile/src/components/chat/ChatConversation.tsx`** and **`ProjectView.tsx`** — merged into `ChatSurface`.
  ProjectView's `activeSessionId` / `started` / `onSessionCreated` in-place machinery is removed; the
  persistent surface makes the plain navigate feel in-place.

### Reused unchanged

`ChatHeader`, `InputBar`, `ChatEmptyState`, `MessageList`, `ProjectContextPanel`, `ProjectChatSessionList`,
`useLiveAgent`, `useChatSessionController`, the zustand `chatSessionStore`, and the module-scope
`runChatStream` (already survives navigation — it keeps writing by `sessionId`).

### File tree (delta)

```
mobile/src/
├── app/(app)/
│   ├── _layout.tsx            (M) mount <ChatSurface/> sibling; route transparency
│   ├── index.tsx             (M) → null focus-reporter
│   ├── chat/[id].tsx         (M) → null focus-reporter
│   └── projects/[id].tsx     (M) → null focus-reporter (param logic → deriveFocus)
├── chat/
│   └── chatFocus.ts          (A) deriveFocus(segments, params)
├── components/chat/
│   ├── ChatSurface.tsx       (A) persistent host (merges the two below)
│   ├── ChatScreen.tsx        (M) + below? slot
│   ├── ChatConversation.tsx  (D)
│   └── ProjectView.tsx       (D)
└── hooks/useChatController.ts (M) caller drops onSessionCreated (no logic change)
```

## Back-stack & URL semantics (web-faithful, free from the router)

- **project → chat**: `router.navigate` (push) → back returns to the project home. Matches web (chatId over
  projectId).
- **landing → chat**: `router.replace` → back skips the now-empty landing.
- **new chat**: `router.replace('/')`.
- **switch conversation** (sidebar): `router.navigate('/chat/b')`.

The body is **not** keyed by `sessionId` — switching between two warm conversations reuses the same
`MessageList`/`FlashList` (data swaps in place, as it did pre-refactor), so there is no automatic scroll-reset.
Per-conversation scroll-reset is deferred to the on-device gate (open question below). The chrome + composer
never remount; the composer's unsent draft is cleared when the target conversation changes so it can't be sent
into the wrong session.

## Morph implementation (reanimated)

- Body region: cross-fade keyed by `focus.kind` / `sessionId` (`FadeIn` / `FadeOut`, ~150 ms — reuse
  ProjectView's `TRANSITION_MS`).
- Composer: `LinearTransition` so it slides when the project below-slot collapses (already proven in
  `ProjectView.tsx:74`).
- Project below-slot (`ProjectChatSessionList`): `FadeOut` on leaving project focus.

## Edge cases / risks

- **Overlay coverage (on-device).** The opaque overlay covers the null Stack chat screens, so there is nothing
  behind it to flash. Confirm the overlay sits correctly under the sidebar Portal and that focus→null (agents)
  cleanly reveals the Stack screen.
- **Switching conversations mid-stream.** `runChatStream` is module-scope and keyed by `sessionId`; the store
  is per-session — the outgoing stream keeps writing to its session while the surface shows another. Already
  the case today; the persistent surface doesn't change it.
- **Deep-link / cold start** into `/chat/[id]` or `/projects/[id]`: `deriveFocus` yields the right mode on
  first frame; existing `useChatController` hydration query fills the body.
- **Keyboard-lift**: composer stays in `KeyboardStickyView` inside the persistent surface — unchanged.
- **Agents gallery / settings**: remain normal opaque Stack screens over the surface; a swap feel there is
  correct (they are genuinely different destinations, not a chat mode).

## Tests

- **Unit (jest, no native) — DONE** — `chat/__tests__/chatFocus.test.ts`: `deriveFocus(pathname)` for `/`,
  `/chat/<id>`, `/projects/<n>`, non-numeric/empty ids → `null`, and non-surface routes (`/agents`,
  `/settings/...`) → `null`. 6 cases, part of the 198-test suite.
- **Integration (`renderRouter`) — DEFERRED** — the spike already proved the persistence pattern headlessly;
  a kept guard against the real `(app)/_layout` is impractical under jest because importing `ChatSurface` pulls
  reanimated + FlashList (the "Worklets not initialized" barrel crash `mobile/CLAUDE.md` warns about). Revisit
  if we add a jest-safe seam.
- **Existing suite — GREEN** — no `ChatConversation`/`ProjectView` tests existed to migrate; the presentational
  `ChatSessionList` / `ProjectChatSessionList` / `ProjectList` tests are unaffected. Full suite: typecheck ·
  lint (0 errors) · **198 jest pass**.
- **On-device (HARD GATE, owner-run) — PENDING** — the four morphs read as in-place (no screen swap), composer
  lifts on focus, overlay reveals agents cleanly, back-stack returns project → chat → project.

## What changes / what's untouched

- **Backend**: none. **Web**: none (mobile-only refactor). **Mobile**: routing model + the two chat screens
  restructured into one persistent surface; net **deletion** of duplicated chrome.

## Open questions (were grill-on; settle at the on-device gate)

1. **Overlay vs `<Slot>`** — RESOLVED to the opaque overlay (see "How it works"); revisit only if the on-device
   pass shows a coverage/gesture issue.
2. **New-chat URL** — kept `/` for `new` (simplest, unchanged).
3. **Message-body key granularity** — `MessageList` currently keys on the `focus.kind`/`messages` swap; confirm
   scroll-reset expectation when returning to an existing chat feels right on device.
4. **Morph parity with web** — implemented as a 150 ms cross-fade (reusing the old `ProjectView` `TRANSITION_MS`);
   confirm against web's curve/duration.
5. **Agents gallery** — stays a separate opaque screen; `deriveFocus('/agents') → null` so the surface hides.
6. **Non-sidebar entry into chat** (notifications, deep links) — re-check against the overlay model on device.
