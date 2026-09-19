> Status: draft · Task: input-bar-controls

# Mobile Input-Bar Controls (ActionsPopover + Deep-Research Toggle) — Research

## Requirement

Port web's chat input-bar toolbar controls — the **ActionsPopover** (tools/actions menu) and the
**deep-research toggle** — into the Onyx React Native mobile composer, at **Tier 2 (Standard)** scope.

## Clarifications

**Q (scope): How much of web's ActionsPopover do we port?**
**A: Tier 2 — Standard.** In scope: deep-research toggle; a tap-to-"force" actions list
(`forced_tool_id`); enable/disable individual tools (`allowed_tool_ids`); a source/connector
selection sub-view (`internal_search_filters`). **Out of scope:** MCP servers, per-MCP-tool
switches, OAuth re-authentication, the admin "More Actions" link, and the action search box.

## Current status & reuse (from codebase scan — verified paths)

**Load-bearing facts (verified against source, not assumed):**

- **The tool + source catalog already rides the wire — no new API needed.** `GET /persona`
  serves `MinimalPersonaSnapshot`, which already carries `tools: list[ToolSnapshot]`
  (`backend/onyx/server/features/persona/models.py:202`) **and**
  `knowledge_sources: list[DocumentSource]` (`:212`). Mobile's `useAgents()`
  (`mobile/src/api/chat/agents.ts`) already hits this endpoint; `MinimalAgent`
  (`mobile/src/chat/agents.ts:15`) is just a hand-picked subset that omits those two fields.
  → **Widen the type; zero new network calls.**
- **Backend already accepts all four send fields.** `SendMessageRequest`
  (`backend/onyx/server/query_and_chat/models.py`) has `allowed_tool_ids` (`:110`),
  `forced_tool_id` (`:111`), `internal_search_filters` (`:115`, a `BaseFilters`), and
  `deep_research` (`:117`). No backend change required (additive optional fields only).
- **`deep_research_enabled` admin flag exists.** `Settings.deep_research_enabled: bool | None`
  (`backend/onyx/server/settings/models.py:50`). Surfaced through `GET /settings`; mobile's
  `useWorkspaceSettings()` (`mobile/src/api/settings.ts`) just doesn't type it yet.

**Mobile — current state:**

- **Composer:** `mobile/src/components/chat/InputBar.tsx` — toolbar control row at lines 119-148.
  LEFT cluster currently holds only the paperclip `Button` (`onPress={() => setPickerOpen(true)}`);
  RIGHT cluster holds send/stop. `InputBar` is stateless about the send body.
- **Composer host:** `mobile/src/components/chat/ChatSurface.tsx` — persistent overlay that mounts
  `InputBar`, wires `onSend`/`onStop` to `useChatController`, computes `personaId`/`liveAgent`, and
  passes the composer draft. This is where new composer-level state threads from.
- **Send body:** `mobile/src/api/chat/stream.ts` `SendMessageBody` sends only
  `{message, chat_session_id, parent_message_id, file_descriptors, deep_research, origin}`.
  `deep_research` is **hardcoded `false`** (`mobile/src/hooks/useChatController.ts:296`).
  `allowed_tool_ids`, `forced_tool_id`, `internal_search_filters` are **missing** — must be added
  to the interface, the body build, and threaded through `submit()` → `runChatStream()`.
- **Overlay primitives:** **no** generalized popover/menu/action-sheet. Closest pattern:
  `mobile/src/components/chat/FilePickerSheet.tsx` — a RN `Modal` bottom sheet (transparent,
  `animationType="slide"`, `rgba(0,0,0,0.4)` scrim `Pressable`, inner `Pressable` sheet
  `rounded-t-20`, composes `LineItemButton` + `Separator`), explicitly "web's FilePickerPopover, as
  a bottom sheet instead of a hover popover" (`:32`), with the iOS "defer action past `onDismiss`"
  gotcha handled. Also available: `@rn-primitives/portal` + `react-native-reanimated`@4.3.1 +
  `react-native-gesture-handler`; `<PortalHost/>` mounted at `mobile/src/app/_layout.tsx:71`;
  `mobile/src/components/sidebar/Sidebar.tsx` already drives a Portal + reanimated + gesture overlay.
- **UI primitives** (`mobile/src/components/ui/`): `Button` (icon-only + label pill; prominence
  primary/secondary/tertiary; has an `active` color cell in `button.styles.ts`), `LineItemButton`
  (selectable full-width row, icon + title + description + `selected`, `leading` slot), `Text`,
  `Icon`, `Separator`, `Spinner`. **No** `Switch`/`Toggle`, **no** `SelectButton` pill primitive.
- **Icons** (`mobile/src/icons/`, hand-rolled `react-native-svg`): has `sliders`/`sliders-small`
  (tools trigger), `plus`, `terminal-small`, `settings`, `search`, `check-small`, `chevron-down`,
  `paperclip`, `x`. **Missing:** `hourglass` (web's deep-research icon) and several per-tool icons
  (web maps `in_code_tool_id` → `SvgSearch`/`SvgGlobe`/`SvgImage`/`SvgTerminal`/`SvgLink`/`SvgCpu`).
- **State:** composer drafts via `mobile/src/hooks/useComposerDraft.ts` + `ComposerDraftProvider`
  keyed `${sessionId}:${projectId}`; zustand stores in `mobile/src/state/` incl. `settingsStore.ts`
  (persisted-to-MMKV prefs). Server state = TanStack Query keyed by `serverUrl`
  (`mobile/src/api/query-keys.ts`); persisted MMKV cache excludes PII keys.
- **Agent model:** `mobile/src/chat/agents.ts` `MinimalAgent` — `id/name/description/starter_messages/
  uploaded_image_id/icon_name/.../labels`, **no `tools`, no `knowledge_sources`**.

**Web — port source of truth:**

- **ActionsPopover:** `web/src/refresh-components/popovers/ActionsPopover/index.tsx` — Opal
  `Popover`/`PopoverMenu` over **Radix** (`@radix-ui/react-popover`), trigger = Opal
  `Button icon={SvgSliders}` tertiary tooltip "Manage Actions", `Popover.Content side="bottom"
  align="start" width="lg"` (~15rem/240px). Primary view: search box + `ActionLineItem` rows
  (`ActionLineItem.tsx`: tap row = **force** the tool → highlighted `selected`; hover `SvgSlash`
  sub-button = enable/disable; `SvgChevronRight` = drill into sources). Secondary `SwitchList.tsx`:
  back-chevron + Enable/Disable-All + rows of label + right-aligned **`Switch`** (source rows show a
  leading `SourceIcon`).
- **Deep research:** Opal `SelectButton variant="select-light" icon={SvgHourglass}
  state={on?"selected":"empty"} foldable={!on}` + label "Deep Research" (pill, folds to icon-only
  when off). State: `web/src/hooks/useDeepResearchToggle.ts` — ephemeral `useState(false)`,
  auto-resets on session/agent change, **not persisted**. Visibility gated by admin
  `deep_research_enabled` (default true) + not-in-project + `hasSearchToolsAvailable(agent.tools)`.
- **Forced-tool pills:** for each id in `forcedToolIds`, a `SelectButton state="selected"` with the
  tool icon + `display_name`, click-to-remove — **shares the pill component** with deep-research.
- **Tool model:** `web/src/lib/tools/interfaces.ts` `ToolSnapshot {id, name, display_name,
  description, in_code_tool_id, mcp_server_id?, chat_selectable, ...}`. Force = zustand
  `useForcedTools` (cleared on agent change; `forced_tool_id = forcedToolIds[0]`). Enable/disable =
  `useAgentPreferences.disabled_tool_ids` — **server-persisted per-agent via PATCH** (not
  localStorage); `allowed_tool_ids = agent tools − disabled_tool_ids`. Sources =
  `filterManager.selectedSources` → `internal_search_filters` (only `source_type` used at Tier 2).

**Known gap (affects the most-used agent):** the **default agent (id 0)** has empty
`knowledge_sources`; web special-cases it to "all accessible sources" via a connectors/CC-pairs
fetch. Mobile has no connectors API today, so the id-0 source sub-view is either empty or needs a
new lightweight connectors query. Flagged for the design phase.

## Industry best practices (how to build the popover on mobile)

- **Bottom sheet vs. anchored popover is the core decision.** 2026 RN guidance: **bottom sheets**
  are the native idiom for contextual actions/filtering anchored to the screen bottom;
  **anchored popovers** point at a trigger and float above, but "must never render off-screen" and
  "must reposition when the keyboard appears." —
  [DEV: Top 5 RN Popover Components 2026](https://dev.to/eira-wexford/top-5-react-native-popover-components-for-developers-2026-1ge4),
  [Reanimated Bottom Sheet docs](https://docs.swmansion.com/react-native-reanimated/examples/bottomsheet/)
- **Anchored popovers are built by measuring the trigger.** The canonical pattern is
  `triggerRef.measure((ox,oy,w,h,px,py) => …)` / `measureInWindow(...)`, then render the panel
  through a Portal/Modal near the root and compute position from the measured rect; place the panel
  "as close to its trigger as possible" and clamp so it never clips. —
  [react-native-popover-view](https://www.npmjs.com/package/react-native-popover-view),
  [Popover UX best practices](https://www.eleken.co/blog-posts/popover-ux)
- **Libraries exist but each has a cost.** `react-native-popover-view` (measures anchor,
  auto-placement engine, pre-styled), `react-native-modal-popover` (RN `Modal`-based), NativeBase
  Popover (WCAG-compliant, headless-capable), plus fully **headless** options that give logic only
  and leave styling to the design system. —
  [DEV article](https://dev.to/eira-wexford/top-5-react-native-popover-components-for-developers-2026-1ge4),
  [SteffeyDev/react-native-popover-view](https://github.com/SteffeyDev/react-native-popover-view)
- **Headless-core is the 2026 recommendation.** Best-in-class popovers expose an unstyled/"headless"
  API — logic (open/close, position, focus) separate from look — so a design system fully owns
  styling. This maps directly to Onyx's token-based primitives. —
  [Base UI Popover](https://base-ui.com/react/components/popover),
  [react-native-popper](https://github.com/intergalacticspacehighway/react-native-popper)
- **The keyboard constraint is decisive here.** The Onyx composer is docked at the very bottom,
  above an open keyboard. An *upward* anchored popover from a bottom trigger is precisely the
  off-screen / keyboard-collision failure mode the guidance warns about, and mobile **already chose**
  a bottom sheet over web's hover popover once (`FilePickerSheet`). This is the central tension the
  three approaches take different positions on.

## Approaches

### Approach A — Simplicity-First: Bottom-sheet ActionsSheet, no new primitives

Clone `FilePickerSheet` into a single `ActionsSheet` bottom sheet; the source sub-view is a swapped
content state (`useState<"actions" | "sources">`) inside the *same* Modal (a back-chevron header
mirrors web's `secondaryView`). Deep-research is a labeled `Button` in the left cluster
(`interaction="active"` for the on state); forced/disabled/source selection is ephemeral React state
in a small `useComposerTools` hook mounted in `ChatSurface`. No generalized popover, no `measure()`,
no `Switch` — the no-hover enable/disable maps to a **row tap = force** + a **trailing icon-`Button`
(`SvgCheckSmall`) = enable/disable** on the same `LineItemButton`; sources are whole-row toggles.
All four fields thread onto the body via one new `sendOptions` arg on `submit()`.
**Size: ~590-680 LOC, 2 PRs.** Biggest bet: selections are session-ephemeral (web persists
`disabled_tool_ids` per-agent server-side) and web's search-tool↔source auto-sync is simplified.

### Approach B — Web-Parity-First: Anchored popover + ported primitives

Build a real **anchored `Popover`** primitive on the Sidebar's Portal + reanimated stack —
`measureInWindow()` the `SvgSliders` trigger, render the 240px panel through `<Portal>`, open
**upward** (documented divergence from Radix `side="bottom"`), `Keyboard.dismiss()` on open, clamp
on-screen, `maxHeight` + `ScrollView`. Port three primitives pixel/behavior-exact via
`port-web-component-to-mobile`: `SelectButton` (stateful pill, shared by deep-research + forced
chips), `Switch` (source rows), and the `Popover` itself. Full Tier-2 parity: the drill-in source
`SwitchList` (back-chevron / Enable-All / rows + switches), **server-persisted per-agent
`disabled_tool_ids`** (new GET+PATCH agent-preferences API), the search-tool↔source coupling, and
correct agent-change resets. **Size: ~2,600-2,900 LOC, 5 PRs.** Highest fidelity and gives the app a
reusable `Popover`/`Switch`/`SelectButton`, at the cost of the app's riskiest new pattern (manual
measure/position/keyboard math on a keyboard-adjacent bottom bar) and its first agent-preferences
write path.

### Approach C — Flexibility-First: Headless sheet + bounded control registry

Three seams carry future growth without over-engineering. (a) Extract a `BottomSheet` shell from the
boilerplate `FilePickerSheet` already hand-rolls (two proven consumers) — renders a sheet today, but
lifecycle (open/dismiss/safe-area/sub-view) is kept separate from positioning so an anchored `mode`
can slot in later without touching menu content. (b) A **bounded toolbar-control registry**
(`buildToolbarControls()`) turns deep-research, forced-tool pills, and future controls (MCP, voice,
tab-reading) into ordered *pill specs* the composer maps over — no `InputBar` surgery per control.
(c) All four fields flow through **one `sendConfig` object** on `submit()`. Ports the two genuinely
missing primitives (`Switch`, `SelectButton`); conservatively extracts **only** the small
backend-wire-coupled `tools` unit (the `ToolSnapshot` type + `in_code_tool_id` constants + pure
`hasSearchToolsAvailable`/`computeAllowedToolIds`) to `@onyx-ai/shared/contracts`, explicitly **not**
the icon map, MCP/OAuth types, or the registry. **Size: ~1,150-1,300 LOC, 3 PRs.** Sources start
without the web auto-sync coupling; per-agent persistence is a documented upgrade seam.

## Cross-comparison

- **Overlay idiom:** A & C use a **bottom sheet** (native idiom, dodges the keyboard/off-screen
  risk, consistent with the adjacent `FilePickerSheet`); B builds an **anchored popover** for
  literal web fidelity and accepts the measure/keyboard risk. C keeps anchoring as a future swap.
- **Primitives:** A introduces **none** (reuses `Button`/`LineItemButton`); B & C both port `Switch`
  + `SelectButton`; B additionally builds a full anchored `Popover` primitive.
- **Persistence & parity of behavior:** B matches web exactly (server-persisted per-agent tool prefs,
  full source auto-sync); A & C keep selections ephemeral-per-conversation first, with persistence
  as a follow-up.
- **Extensibility:** C is built for the four *named* future controls (MCP/voice/tab-reading + more)
  to land additively; A would reopen `InputBar` + the sheet for each; B gives reusable primitives but
  no control registry.
- **Cost:** A ≈ 2 PRs / ~650 LOC · C ≈ 3 PRs / ~1,200 LOC · B ≈ 5 PRs / ~2,700 LOC.
- **Shared no-hover enable/disable UX** (all three): row tap = force, a distinct trailing target =
  enable/disable (B/C via a `Switch`, A via a check-`Button`); the default-agent (id 0) empty-sources
  gap is a shared open item.

## Chosen approach

**Approach B — Web-Parity-First** (selected at GATE 1, 2026-07-16). Consistent with the
owner-enforced WEB-PARITY PRINCIPLE and the owner's track record of choosing full parity on
PR3/4/5/7/8.

Commitments carried into design:
- **Anchored `Popover` primitive** built on the Sidebar's Portal + reanimated stack —
  `measureInWindow()` the `SvgSliders` trigger, render a ~240px panel through `<Portal>`, open
  **upward** (documented divergence from Radix `side="bottom"` — forced by the bottom-docked bar),
  `Keyboard.dismiss()` on open, clamp on-screen, `maxHeight` + `ScrollView`.
- **Three ported primitives** via `port-web-component-to-mobile`: `SelectButton` (stateful pill,
  shared by the deep-research toggle **and** forced-tool chips), `Switch` (source sub-view rows),
  and the anchored `Popover` itself.
- **Full Tier-2 parity behavior:** the drill-in source `SwitchList` (back-chevron / Enable-All /
  rows + switches), **server-persisted per-agent `disabled_tool_ids`** (new GET+PATCH
  agent-preferences API on mobile — the app's first agent-preferences write path), the
  search-tool↔source coupling, and correct agent-change / session-change resets.
- Deep-research stays **ephemeral** (matches web), gated by `deep_research_enabled` +
  `hasSearchToolsAvailable(agent.tools)`.

Open items to resolve in design:
- **Default agent (id 0) sources gap** — empty `knowledge_sources`; needs a lightweight connectors
  query for the "all accessible sources" case (affects the most-used agent).
- The anchored-popover keyboard/off-screen behavior is the highest-risk piece → an on-device gate.

Est. **~2,600-2,900 LOC across 5 PRs** (primitives → anchored popover → state layer →
ActionsPopover/sources → wire-up).
