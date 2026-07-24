> Status: active · Task: input-bar-controls

# Mobile Input-Bar Controls (ActionsPopover + Deep-Research Toggle) — Implementation Plan

## Issues to Address

The mobile chat composer can type, attach files, and send — but it cannot control **which tools the
agent uses**, **force a specific tool**, choose **which knowledge sources to search**, or turn on
**deep research**. Web has all of this in its input-bar toolbar. This change ports that toolbar to
mobile at **Tier-2 (Standard)** scope, web-parity (Approach B): a **deep-research toggle** and an
**anchored ActionsPopover** (force-a-tool + enable/disable tools + a source-selection sub-view).
Outcome: the mobile send request carries `deep_research`, `forced_tool_id`, `allowed_tool_ids`, and
`internal_search_filters`, and per-agent `disabled_tool_ids` persists server-side (shared with web).
Out of scope: MCP servers/tools, OAuth re-auth, the admin "More Actions" link, and the action search
box.

## Important Notes

- **No backend work, no migration.** All four send fields already exist on `SendMessageRequest`
  (`backend/onyx/server/query_and_chat/models.py:110,111,115,117`). Per-agent `disabled_tool_ids`
  already has a table (`assistant__user_specific_config`, `backend/onyx/db/models.py:4058`) and
  endpoints `GET /user/assistant/preferences` + `PATCH /user/assistant/{id}/preferences`
  (`backend/onyx/server/manage/users.py:1283,1300`, both `BASIC_ACCESS`).
- **The tool + source catalog is already on the wire.** `GET /persona` serves
  `MinimalPersonaSnapshot` with `tools: list[ToolSnapshot]` + `knowledge_sources:
  list[DocumentSource]` (`backend/onyx/server/features/persona/models.py:202,212`). Mobile's
  `useAgents()` already calls it; `MinimalAgent` (`mobile/src/chat/agents.ts:15`) just omits the two
  fields. → widen the type, **no new fetch for tools**.
- **`deep_research` is hardcoded `false`** today (`mobile/src/hooks/useChatController.ts:296`);
  `allowed_tool_ids`/`forced_tool_id`/`internal_search_filters` are missing from `SendMessageBody`
  (`mobile/src/api/chat/stream.ts`).
- **Mobile has no popover/Switch/SelectButton primitive.** Build on the proven Portal + reanimated
  stack (`mobile/src/components/sidebar/Sidebar.tsx`; `<PortalHost/>` at `mobile/src/app/_layout.tsx:71`).
  `mobile/src/components/ui/line-item-button.tsx` already has a `rightChildren` trailing slot (from
  `content.tsx`) — no change needed to host the enable/disable control + chevron. Mobile `Button`
  drops hover (`ButtonInteraction = rest|active`), so the `SelectButton` matrix + `foldable` must be
  **state/press-driven, not hover-driven**.
- **Web-parity gotchas to port exactly** (from `03-detailed-design.md`): the search-tool↔source
  reconcile is gated by `sourcesInitialized` and only toggles when inconsistent
  (`web/.../ActionsPopover/index.tsx:742-770`) — port the guard or it render-loops;
  `useDeepResearchToggle` preserves the flag on the null→new-session transition via a ref
  (`web/src/hooks/useDeepResearchToggle.ts:31-44`); `computeAllowedToolIds` returns `null` (not `[]`)
  when nothing is disabled; forced tools are a single-element selection.
- **The anchored popover on a keyboard-adjacent bottom bar is the highest risk** and needs an
  on-device dev build to verify (agent can't). Fallback: swap the `Popover` container for the
  `FilePickerSheet` bottom-sheet shell — the `ActionsPopover` content is renderer-agnostic.
- **Default agent (id 0)** has empty `knowledge_sources`; source list comes from a new
  `useConnectorSources` (GET `/manage/connector-status`, any chat-accessible user). Federated
  connectors (EE `/federated`) deferred.
- **Icons:** 8 SVGs must be added to `mobile/src/icons/` — `hourglass`, `globe`, `cpu`, `link`,
  `server`, `plug`, `unplug`, `slash` (exact web path data below).
- **Standards** (`mobile/CLAUDE.md`): reuse `Text`/`Icon`/`Button`/`LineItemButton`; NativeWind
  semantic tokens only; spacing class number = px; TanStack Query keyed by `serverUrl`, PII keys
  MMKV-excluded (sources/prefs are safe to persist; selection state stays in provider, not Query);
  import leaf components in jest (reanimated barrels crash the runner).

## Implementation Strategy

Ordered so each group is a coherent, independently-mergeable change (Phase 5 bundles into PRs).

1. **Send-body plumbing + type widening (foundation).** Widen `SendMessageBody`
   (`mobile/src/api/chat/stream.ts`) with `allowed_tool_ids?`, `forced_tool_id?`,
   `internal_search_filters?` + a new `InternalSearchFilters` type. Widen `MinimalAgent`
   (`mobile/src/chat/agents.ts`) with `tools` + `knowledge_sources`. Add `deep_research_enabled?` to
   `WorkspaceSettings` (`mobile/src/api/settings.ts`). Extend `useChatController.submit`
   (`mobile/src/hooks/useChatController.ts:228`) with a `toolOptions?: ChatToolOptions` arg; replace
   the hardcoded `deep_research: false` (`:296`) and populate the three new fields in the body
   (`:291`). Add the pure `mobile/src/chat/tools.ts` (`ToolSnapshot`, tool-id constants, predicates,
   `computeAllowedToolIds`, `getIconForToolId`) and `mobile/src/chat/sources.ts` (`DocumentSource`,
   `SOURCE_META`, `buildInternalSearchFilters`).

2. **Icons.** Add the 8 `react-native-svg` icons to `mobile/src/icons/` following the
   `sliders.tsx`/`types.ts` shape (default export, `IconProps`, `stroke="currentColor"`), using the
   verbatim web path data (see Appendix). `link` uses viewBox `0 0 17 9` + `rotate(315deg)`; `slash`
   renders two `<Path>`s.

3. **UI primitives.** Port via `port-web-component-to-mobile`:
   - `mobile/src/components/ui/select-button.tsx` + `select-button.styles.ts` — `SELECT_COLORS`
     stateful literal matrix (`select-light`, `empty`/`selected`, `rest`/`active`/`disabled`) +
     `resolveSelectState`, mirroring `button.styles.ts`; `foldable` = conditional label render.
   - `mobile/src/components/ui/switch.tsx` — reanimated track (32×18) + thumb (14×14), `checked`
     bg `action-link-05`.
   - `mobile/src/components/ui/popover.tsx` — anchored panel: `measureInWindow` the anchor, `<Portal>`
     render, upward positioning + on-screen clamp + `maxHeight`/scroll, `Keyboard.dismiss()` on open,
     re-measure on keyboard/rotation, outside-tap close.

4. **State layer.** `mobile/src/api/chat/agentPreferences.ts` (GET/PATCH) +
   `mobile/src/api/chat/connectors.ts` (connector-status). Hooks:
   `mobile/src/hooks/useAgentPreferences.ts` (TanStack Query GET + a `useMutation` PATCH using the
   canonical optimistic pattern — `onMutate`: cancel + snapshot + `setQueryData`; `onError`: restore
   snapshot; `onSettled`: invalidate — plus a short debounce for rapid toggles),
   `useConnectorSources.ts`, `useDeepResearchToggle.ts` (port with the ref-guarded resets),
   `useForcedTools.ts` (single-force, agent-reset), `useSourceSelection.ts` (ephemeral, self-init to
   all). Add query keys (`mobile/src/api/query-keys.ts`). `mobile/src/state/ComposerToolsProvider.tsx`
   aggregates them + exposes `resolveToolOptions()`.

5. **Deep-research control (first visible slice).** `mobile/src/components/chat/ToolbarControls.tsx`
   renders the deep-research `SelectButton` (gated by `deep_research_enabled &&
   hasSearchToolsAvailable`). Wire `ComposerToolsProvider` into `ChatSurface`
   (`mobile/src/components/chat/ChatSurface.tsx`) and render `ToolbarControls` in `InputBar`'s left
   cluster (`mobile/src/components/chat/InputBar.tsx:119-127`); thread `resolveToolOptions()` into
   `sendWithAttachments` → `submit`. Deep research works end-to-end at this step.

6. **ActionsPopover — tools list + force + enable/disable.**
   `mobile/src/components/chat/ActionsPopover.tsx` (composes `Popover`, owns `open`/`subView`) +
   `ActionLineItem.tsx` (tap=force with the disable-clears-force guard; trailing `Switch` =
   enable/disable; chevron for search drill-in). Add the Actions trigger + forced-tool pills to
   `ToolbarControls`. Wire `allowed_tool_ids`/`forced_tool_id` through the provider.

7. **Source sub-view + coupling.** `mobile/src/components/chat/SourceSwitchList.tsx` +
   `SourceIcon.tsx`; in-place body swap in `ActionsPopover`. First wire plain source→filter selection
   (`internal_search_filters`); then add the search-tool↔source coupling as an isolated step, porting
   the `sourcesInitialized` guard + single-force + `previouslyEnabledSourcesRef` idempotency exactly.

## Tests

**Primary type: External-Dependency Unit / jest unit** (mobile uses `jest-expo`; no Onyx-container
E2E for mobile). Concentrate on the pure logic and the two loop-prone reducers — the anchored-popover
rendering is verified on-device, not in jest.

- **Pure logic (`mobile/src/chat/__tests__/`):** `computeAllowedToolIds` (null when nothing disabled,
  list when some disabled, never `[]`), `hasSearchToolsAvailable`, `displayableTools` (drops MCP /
  non-`chat_selectable` / FileReader), `buildInternalSearchFilters` (`{source_type}` vs `null`).
- **`useDeepResearchToggle`:** the reset matrix — preserves on null→new-session, resets on real
  session switch, always resets on agent change, toggles correctly.
- **Source-coupling reducer:** enabling a source pins search, disabling the last source unpins it,
  enable-all/disable-all, and **no oscillation** once `initialized` (the guard).
- **`useAgentPreferences`:** optimistic set then PATCH then invalidate; sends the full `disabled_tool_ids`
  array; failure rolls back.
- **`ToolbarControls` gating:** deep-research pill hidden when `deep_research_enabled` false or no
  search tool; Actions trigger hidden when the agent has no displayable tools.
- **On-device gate (owner-run, not automated):** anchored popover opens upward without keyboard
  collision / off-screen clipping across iOS + Android after `expo prebuild`; the fallback swap to the
  bottom-sheet shell if unstable.

## Appendix — exact SVG path data for the 8 new icons

viewBox `0 0 16 16`, `stroke="currentColor"`, `strokeWidth={1.5}`, `fill="none"`, unless noted.

- **hourglass:** `M8 8L4.44793 5.72667C4.06499 5.48159 3.83333 5.05828 3.83333 4.60364V1.83333H12.1667V4.60364C12.1667 5.05828 11.935 5.48159 11.5521 5.72667L8 8ZM8 8L11.5521 10.2733C11.935 10.5184 12.1667 10.9417 12.1667 11.3963V14.1667H3.83333V11.3963C3.83333 10.9417 4.06499 10.5184 4.44793 10.2733L8 8ZM13.5 14.1667H2.5M13.5 1.83333H2.5`
- **globe:** `M14.6667 8C14.6667 11.6819 11.6819 14.6667 8 14.6667M14.6667 8C14.6667 4.3181 11.6819 1.33333 8 1.33333M14.6667 8H1.33334M8 14.6667C4.31811 14.6667 1.33334 11.6819 1.33334 8M8 14.6667C9.66753 12.8411 10.6152 10.472 10.6667 8C10.6152 5.52802 9.66753 3.1589 8 1.33333M8 14.6667C6.33249 12.8411 5.38484 10.472 5.33334 8C5.38484 5.52802 6.33249 3.1589 8 1.33333M1.33334 8C1.33334 4.3181 4.31811 1.33333 8 1.33333`
- **cpu:** `M6.09091 1V2.90909M9.90909 1V2.90909M6.09091 13.0909V15M9.90909 13.0909V15M13.0909 6.09091H15M13.0909 9.27273H15M1 6.09091H2.90909M1 9.27273H2.90909M4.18182 2.90909H11.8182C12.5211 2.90909 13.0909 3.47891 13.0909 4.18182V11.8182C13.0909 12.5211 12.5211 13.0909 11.8182 13.0909H4.18182C3.47891 13.0909 2.90909 12.5211 2.90909 11.8182V4.18182C2.90909 3.47891 3.47891 2.90909 4.18182 2.90909ZM6 6H10V10H6V6Z`
- **link** (viewBox `0 0 17 9`, `transform={[{ rotate: "315deg" }]}` on `<Svg>`): `M10.0833 0.75H12.0833C12.5211 0.75 12.9545 0.836219 13.3589 1.00373C13.7634 1.17125 14.1308 1.41678 14.4404 1.72631C14.7499 2.03584 14.9954 2.4033 15.1629 2.80772C15.3304 3.21214 15.4167 3.64559 15.4167 4.08333C15.4167 4.52107 15.3304 4.95453 15.1629 5.35894C14.9954 5.76336 14.7499 6.13083 14.4404 6.44036C14.1308 6.74988 13.7634 6.99542 13.3589 7.16293C12.9545 7.33045 12.5211 7.41667 12.0833 7.41667H10.0833M6.08333 7.41667H4.08333C3.64559 7.41667 3.21214 7.33045 2.80772 7.16293C2.4033 6.99542 2.03584 6.74988 1.72631 6.44036C1.10119 5.81523 0.75 4.96739 0.75 4.08333C0.75 3.19928 1.10119 2.35143 1.72631 1.72631C2.35143 1.10119 3.19928 0.75 4.08333 0.75H6.08333M5.41667 4.08333H10.75`
- **server:** `M4 4H4.00666M4 12H4.00666M2.66666 1.33334H13.3333C14.0697 1.33334 14.6667 1.9303 14.6667 2.66668V5.33334C14.6667 6.06972 14.0697 6.66668 13.3333 6.66668H2.66666C1.93028 6.66668 1.33333 6.06972 1.33333 5.33334V2.66668C1.33333 1.9303 1.93028 1.33334 2.66666 1.33334ZM2.66666 9.33334H13.3333C14.0697 9.33334 14.6667 9.9303 14.6667 10.6667V13.3333C14.6667 14.0697 14.0697 14.6667 13.3333 14.6667H2.66666C1.93028 14.6667 1.33333 14.0697 1.33333 13.3333V10.6667C1.33333 9.9303 1.93028 9.33334 2.66666 9.33334Z`
- **plug:** `M12 10.5H15M12 10.5V12.5M12 10.5V5.5M12 3.5H8.5C6.01472 3.5 4 5.51472 4 8M12 3.5V5.5M12 3.5V2M12 12.5H8.5C6.01472 12.5 4 10.4853 4 8M12 12.5V14M4 8H1M12 5.5H15`
- **unplug:** `M1 1L5.0778 5.0778M15 15L12 12M15 10.5H14M12 12.5H8.5C6.01472 12.5 4 10.4853 4 8M12 12.5V14M12 12.5V12M12 3.5H8.5C8.04537 3.5 7.60649 3.56742 7.1928 3.6928M12 3.5V5.5M12 3.5V2M12 5.5H15M12 5.5V8.5M4 8H1M4 8C4 6.88463 4.40579 5.86403 5.0778 5.0778M5.0778 5.0778L12 12`
- **slash** (two `<Path>`s): `M14.6667 8C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 8C1.33333 4.3181 4.3181 1.33333 7.99999 1.33333C11.6819 1.33333 14.6667 4.3181 14.6667 8Z` and `M3.5 3.5L12.5 12.5`

---

## Plan Challenge Results

Run 2026-07-16. Web-verification searches executed for checks 3 & 4.

### 1. Extendability & Scalability: PASS (minor note)
Tool/source lists are small and bounded (a handful of tools per agent; sources bounded by
connectors) — no scale concern. The three ported primitives (`Popover`/`Switch`/`SelectButton`) are
reusable infra for every future menu. **Note:** adding a *new* toolbar control later (MCP quick-toggle,
voice, tab-reading) touches `ToolbarControls.tsx` + `ActionsPopover.tsx` directly — Approach B has no
data-driven control registry (that was Approach C's seam, consciously not chosen). Acceptable: MCP is
an explicitly-scoped future PR, and the send-body is already extended through one `ChatToolOptions`
object, so new fields extend one struct.

### 2. Fragility: CONCERN (identified + mitigated)
Three brittle points, all called out with mitigations: **(a)** the search-tool↔source coupling can
render-loop — mitigated by porting the `sourcesInitialized` guard + "only toggle if inconsistent"
idempotency and shipping plain source-selection *before* the coupling as an isolated, tested step;
**(b)** the anchored popover's keyboard/off-screen math — mitigated by the on-device gate + the
bottom-sheet-shell fallback (content is renderer-agnostic); **(c)** the `useDeepResearchToggle`
null→new-session preservation — mitigated by porting the ref guard verbatim + a unit test on the reset
matrix. No hidden single points of failure; the feature degrades gracefully (controls hidden when
their gates fail; all four send fields optional).

### 3. Industry Standard: VERIFIED
Searched RN anchored-popover + keyboard practices and the TanStack optimistic-update pattern.
Confirmed standard: an anchored popover **measures the trigger → renders through a Portal near root →
auto-positions to stay in the viewport → is keyboard-aware** (exactly the `popover.tsx` design). And
the per-agent-prefs write uses the **canonical `onMutate`(cancel+snapshot+`setQueryData`) /
`onError`(rollback) / `onSettled`(invalidate) + debounce** optimistic pattern. The one divergence —
hand-rolling the popover instead of adopting `react-native-popover-view` — is justified: we need
pixel-parity with Opal/Radix and NativeWind-token styling, and mobile already hand-rolls its overlays
(`Sidebar`, `FilePickerSheet`); a pre-styled third-party popover would fight the token system.
Sources: [RN popover components 2026](https://dev.to/eira-wexford/top-5-react-native-popover-components-for-developers-2026-1ge4),
[react-native-popover-view](https://www.npmjs.com/package/react-native-popover-view),
[Margelo keyboard deep-dive](https://blog.margelo.com/deep-dive-in-keyboard-handling),
[TanStack optimistic updates](https://tanstack.com/query/latest/docs/framework/react/guides/optimistic-updates).

### 4. Fact Check: PASS
Every factual claim is code-verified with file:line: backend accepts all four send fields
(`models.py:110,111,115,117`); the prefs table + endpoints exist (`db/models.py:4058`,
`manage/users.py:1283,1300`); `/persona` already serves `tools`+`knowledge_sources`
(`persona/models.py:202,212`); `deep_research_enabled` exists (`settings/models.py:50`); mobile
`MinimalAgent` omits both fields (`mobile/src/chat/agents.ts:15`); `deep_research` is hardcoded false
(`useChatController.ts:296`). The two "industry-standard" claims are now web-verified (check 3). No
unverified claims remain.

### 5. Maintainability: PASS
Follows existing mobile conventions exactly — primitives in `components/ui/`, chat components in
`components/chat/`, pure logic in `chat/`, hooks in `hooks/`, TanStack Query keyed by `serverUrl`,
`port-web-component-to-mobile` for the ports. Each of the ~18 new files is small and
single-responsibility. 18 files is a large surface, but it's split across 5 review-sized PRs and each
file's web counterpart is cited, so a newcomer can follow the mapping in <15 min.

### 6. Patch vs. Fix: PROPER FIX
This is a net-new capability, not a symptom workaround. It fixes the root cause ("mobile can't control
tools/sources/deep-research") by adding the real controls and wiring the **real** backend fields —
`deep_research` moves from a hardcoded `false` to the actual toggle value; `allowed_tool_ids`/
`forced_tool_id`/`internal_search_filters` are populated from real UI state; `disabled_tool_ids`
persists to the same server record web uses. No errors suppressed, no timeouts bumped, no fake loading
states. **No user decision required.**

**Verdict: all six checks clear (one identified-and-mitigated fragility concern, no blocking
failures, no patch). Plan is execution-ready.**
