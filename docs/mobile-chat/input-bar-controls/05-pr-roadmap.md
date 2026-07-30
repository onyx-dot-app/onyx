> Status: active · Task: input-bar-controls · Source plan: 04-implementation-plan.md

# Mobile Input-Bar Controls (ActionsPopover + Deep-Research Toggle) — PR Roadmap

Approach **B — Web-Parity-First**. Four review-sized PRs, ordered so the **deep-research toggle works
end-to-end at PR 2** (the walking skeleton) and the tools menu + sources layer on after. Each PR
leaves `main` releasable; new controls are only visible when their gates pass, so partial merges are
inert without a feature flag.

> **PR 1 merges the former "plumbing" and "primitives" PRs** into one foundation (owner decision at
> GATE 3, 2026-07-16). It is a no-runtime-surface PR (types, pure logic, primitives, icons — nothing
> wired into chat), so it stays coherent, but it lands **above** the ~500-700 band (~950-1,150 LOC).

## Overview

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 1 | `feat(mobile): tool-options foundation — send-body, contracts, primitives, icons` | ~950-1,150 | — | Send-body/type widening + pure `tools.ts`/`sources.ts` + `SelectButton`/`Switch` + 8 icons. No chat wiring. |
| 2 | `feat(mobile): deep-research toggle` | ~450-550 | PR 1 | **Walking skeleton** — deep research works end-to-end via the input-bar pill. |
| 3 | `feat(mobile): actions popover — tools, force + enable/disable` | ~650-750 | PR 2 | Anchored `Popover` + `ActionsPopover` tool list; `forced_tool_id` + server-persisted `allowed_tool_ids`. |
| 4 | `feat(mobile): actions popover — source selection + search coupling` | ~550-650 | PR 3 | Source sub-view + search↔source coupling; `internal_search_filters`. |

## Sequence

```
PR1 foundation (send-body + pure contracts + SelectButton/Switch + icons)
      │
      ▼
PR2 deep-research toggle (walking skeleton) ─► PR3 ActionsPopover (tools) ─► PR4 sources + coupling
```

PR 1 is the shared foundation (no runtime surface). PR 2 is the thin end-to-end slice that proves the
composer→provider→submit shape. PR 3 introduces the anchored popover (the on-device gate) with its
first real consumer. PR 4 completes Tier-2.

---

## PR 1 — `feat(mobile): tool-options foundation — send-body, contracts, primitives, icons`

- **Goal:** Land the entire no-runtime-surface foundation — wire types, pure logic, reusable
  primitives, and icons — so PR 2-4 only add state + wiring. Nothing is visible in the app yet.
- **Scope (in):**
  - **Send-body + types:** widen `SendMessageBody` with `allowed_tool_ids?`/`forced_tool_id?`/
    `internal_search_filters?` + the `InternalSearchFilters` type; widen `MinimalAgent` with
    `tools`/`knowledge_sources`; add `deep_research_enabled?` to `WorkspaceSettings`.
  - **Submit threading:** `submit(text, files?, onAccepted?, toolOptions?)`; replace hardcoded
    `deep_research: false` and populate the three new body fields (no-op when `toolOptions` absent).
  - **Pure modules:** `chat/tools.ts` (`ToolSnapshot`, tool-id constants, predicates,
    `computeAllowedToolIds`, `getIconForToolId`) + `chat/sources.ts` (`DocumentSource`, `SOURCE_META`,
    `buildInternalSearchFilters`).
  - **Primitives:** `select-button.tsx` + `select-button.styles.ts` (`SELECT_COLORS` literal matrix +
    `resolveSelectState`, `select-light`, `foldable` via conditional label render — no hover);
    `switch.tsx` (reanimated track/thumb).
  - **Icons:** the 8 SVGs (`hourglass`, `globe`, `cpu`, `link`, `server`, `plug`, `unplug`, `slash`)
    with the verbatim path data from `04`'s appendix.
- **Out of scope:** the anchored `Popover` (PR 3, with its consumer); any hooks, provider, or chat
  wiring; any network calls beyond the existing send path.
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `mobile/src/api/chat/stream.ts` | modified | send-body fields + `InternalSearchFilters` |
  | `mobile/src/chat/agents.ts` | modified | widen `MinimalAgent` |
  | `mobile/src/api/settings.ts` | modified | `deep_research_enabled` |
  | `mobile/src/hooks/useChatController.ts` | modified | `submit` `toolOptions` arg + body build |
  | `mobile/src/chat/tools.ts` | new | tool contract + predicates |
  | `mobile/src/chat/sources.ts` | new | source contract + filter builder |
  | `mobile/src/components/ui/select-button.tsx` + `.styles.ts` | new | pill primitive |
  | `mobile/src/components/ui/switch.tsx` | new | toggle primitive |
  | `mobile/src/icons/{hourglass,globe,cpu,link,server,plug,unplug,slash}.tsx` | new | 8 icons |
  | `mobile/src/chat/__tests__/tools.test.ts` | new | pure-logic tests |
  | `mobile/src/components/ui/__tests__/select-button.test.tsx` | new | state/matrix render |
- **Est. size:** ~950-1,150 LOC. **Above the band by owner choice (merged plumbing + primitives).**
  It stays coherent because nothing here is wired into the running app — it's all foundation. If it
  feels too large in review, the natural re-split is back into "plumbing/contracts" vs
  "primitives/icons".
- **Depends on:** —
- **Feature-flag state:** N/A — additive/optional fields; `deep_research` still effectively `false`
  (no UI sets it); primitives unused. Backwards compatible.
- **Tests on merge:** jest unit — `computeAllowedToolIds` (null vs list, never `[]`),
  `hasSearchToolsAvailable`, `displayableTools` filtering, `buildInternalSearchFilters`; a controller
  test asserting `submit` threads `toolOptions`; `SelectButton` empty/selected/disabled cell
  resolution; `Switch` toggle; icons render at default size.
- **Drift checkpoint:** re-confirm the backend `SendMessageRequest` field names/types
  (`models.py:110-117`), that `/persona` still serves `tools`+`knowledge_sources`, and that
  `button.styles.ts`'s matrix shape (mirrored by `SELECT_COLORS`) is unchanged. Use
  `port-web-component-to-mobile` for `SelectButton`/`Switch`.

## PR 2 — `feat(mobile): deep-research toggle` (walking skeleton)

- **Goal:** Prove the composer→provider→submit path end-to-end with the simplest control.
- **Scope (in):**
  - `useDeepResearchToggle` (port with the ref-guarded null→new-session preservation + agent reset).
  - `ComposerToolsProvider` (deep-research only for now; `resolveToolOptions()` returns
    `deep_research`, the rest null).
  - `ToolbarControls` rendering just the deep-research `SelectButton` (gated by
    `deep_research_enabled && hasSearchToolsAvailable`).
  - Wire `ComposerToolsProvider` into `ChatSurface`; render `ToolbarControls` in `InputBar`'s left
    cluster; thread `resolveToolOptions()` into `sendWithAttachments`→`submit`.
- **Out of scope:** the Actions menu, popover, tools/sources state.
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `mobile/src/hooks/useDeepResearchToggle.ts` | new | ephemeral toggle + resets |
  | `mobile/src/state/ComposerToolsProvider.tsx` | new | provider (deep-research slice) |
  | `mobile/src/components/chat/ToolbarControls.tsx` | new | deep-research pill only |
  | `mobile/src/components/chat/InputBar.tsx` | modified | render `ToolbarControls` |
  | `mobile/src/components/chat/ChatSurface.tsx` | modified | provider + thread options |
  | `mobile/src/hooks/__tests__/useDeepResearchToggle.test.ts` | new | reset matrix |
- **Est. size:** ~450-550 LOC.
- **Depends on:** PR 1 (submit/plumbing, `SelectButton`, hourglass icon).
- **Feature-flag state:** N/A — gated by the `deep_research_enabled` admin setting; invisible when off.
- **Tests on merge:** jest — the reset matrix (preserve on null→new-session, reset on real switch +
  agent change); `ToolbarControls` gating (pill hidden without the setting or a search tool). Manual:
  toggle on → send → request carries `deep_research: true`.
- **Drift checkpoint:** confirm the `ChatSurface`/`InputBar` seams from PR 1 are unchanged and that
  `sessionId`/`agentId` are available where the provider mounts.

## PR 3 — `feat(mobile): actions popover — tools, force + enable/disable`

- **Goal:** The anchored Actions menu with tool forcing + server-persisted enable/disable.
- **Scope (in):**
  - `popover.tsx` (anchored: `measureInWindow`, Portal, upward + clamp + `maxHeight`/scroll,
    `Keyboard.dismiss()` on open, re-measure on keyboard/rotation).
  - `ActionsPopover.tsx` (composes `Popover`, owns `open`/`subView`) + `ActionLineItem.tsx` (tap=force
    with disable-clears-force guard; trailing `Switch` enable/disable; search-drill-in chevron).
  - `useForcedTools` + `useAgentPreferences` (+ `api/chat/agentPreferences.ts`, optimistic
    `onMutate`/`onError`/`onSettled` + debounce).
  - Extend `ComposerToolsProvider` + `ToolbarControls` (Actions trigger + forced-tool pills); wire
    `forced_tool_id` + `allowed_tool_ids`.
- **Out of scope:** the source sub-view + coupling (PR 4); MCP/OAuth rows; action search box.
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `mobile/src/components/ui/popover.tsx` | new | anchored popover primitive |
  | `mobile/src/components/chat/ActionsPopover.tsx` | new | menu shell + primary list |
  | `mobile/src/components/chat/ActionLineItem.tsx` | new | tool row (force + enable/disable) |
  | `mobile/src/hooks/useForcedTools.ts` | new | single-force state |
  | `mobile/src/hooks/useAgentPreferences.ts` | new | GET + optimistic PATCH |
  | `mobile/src/api/chat/agentPreferences.ts` | new | prefs API wrappers |
  | `mobile/src/api/query-keys.ts` | modified | `agentPreferences` key |
  | `mobile/src/state/ComposerToolsProvider.tsx` | modified | force + disabled slices |
  | `mobile/src/components/chat/ToolbarControls.tsx` | modified | Actions trigger + forced pills |
- **Est. size:** ~650-750 LOC. Near the top of the band and **can't split further** — the anchored
  `Popover` has no other consumer, so building it apart from `ActionsPopover` would leave an
  untestable PR; force + enable/disable share the same row and provider.
- **Depends on:** PR 2.
- **Feature-flag state:** N/A — the Actions trigger only renders when the agent has displayable tools.
- **Tests on merge:** jest — `useForcedTools` single-force + agent reset; `useAgentPreferences`
  optimistic set → PATCH full array → invalidate → rollback on error; `ActionLineItem` force +
  disable-clears-force. **On-device gate (owner-run):** anchored popover opens upward without keyboard
  collision / off-screen clipping on iOS + Android after `expo prebuild`; fallback = swap the popover
  container for the `FilePickerSheet` bottom-sheet shell.
- **Drift checkpoint:** confirm the prefs endpoints (`GET /user/assistant/preferences`,
  `PATCH /user/assistant/{id}/preferences`) are unchanged; decide the final no-hover enable/disable
  affordance (default: trailing `Switch`) before coding the row.

## PR 4 — `feat(mobile): actions popover — source selection + search coupling`

- **Goal:** Complete Tier-2 with the source sub-view and the web-faithful search↔source coupling.
- **Scope (in):**
  - `SourceSwitchList.tsx` (back + Enable-All/Disable-All + `Switch` rows) + `SourceIcon.tsx`;
    in-place body swap in `ActionsPopover`.
  - `useConnectorSources` (+ `api/chat/connectors.ts`, GET `/manage/connector-status`) +
    `useSourceSelection` (ephemeral, self-init to all).
  - Wire `internal_search_filters`; then add the search-tool↔source coupling as an isolated commit
    (port the `sourcesInitialized` guard + single-force + `previouslyEnabledSourcesRef` idempotency).
  - Populate `SOURCE_META`; default-agent (id 0) uses the connector list.
- **Out of scope:** federated connectors (EE `/federated`) — documented gap.
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `mobile/src/components/chat/SourceSwitchList.tsx` | new | source sub-view |
  | `mobile/src/components/chat/SourceIcon.tsx` | new | source glyph |
  | `mobile/src/hooks/useConnectorSources.ts` | new | connector-status query |
  | `mobile/src/api/chat/connectors.ts` | new | connector-status wrapper |
  | `mobile/src/hooks/useSourceSelection.ts` | new | selection + coupling |
  | `mobile/src/api/query-keys.ts` | modified | `connectorSources` key |
  | `mobile/src/chat/sources.ts` | modified | fill `SOURCE_META` |
  | `mobile/src/components/chat/ActionsPopover.tsx` | modified | mount sub-view + chevron |
  | `mobile/src/state/ComposerToolsProvider.tsx` | modified | source slice + filters |
  | `mobile/src/hooks/__tests__/useSourceSelection.test.ts` | new | coupling reducer |
- **Est. size:** ~550-650 LOC.
- **Depends on:** PR 3.
- **Feature-flag state:** N/A.
- **Tests on merge:** jest — `buildInternalSearchFilters` (`{source_type}` vs null); the coupling
  reducer (enable source→pin search, disable-last→unpin, enable-all/disable-all, **no oscillation**
  once initialized). Manual: pick sources → send → request carries
  `internal_search_filters.source_type`.
- **Drift checkpoint:** confirm `/manage/connector-status` is reachable by a chat-accessible user and
  its `BasicCCPairInfo{source}` shape; re-read the web coupling logic
  (`ActionsPopover/index.tsx:742-810`) immediately before porting it, since it is the loop-prone part.
