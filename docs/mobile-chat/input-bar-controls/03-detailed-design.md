> Status: active · Task: input-bar-controls

# Mobile Input-Bar Controls (ActionsPopover + Deep-Research Toggle) — Detailed Design

Approach **B — Web-Parity-First**. All paths are repo-relative. Web references are the port source of
truth; mobile mirrors look **and** structure, documenting platform-driven divergences.

---

## Database design

**N/A — no schema changes.** The only persisted state is per-agent `disabled_tool_ids`, and the
table + endpoints already exist:

- Table `assistant__user_specific_config` (`backend/onyx/db/models.py:4058-4069`): composite PK
  `(assistant_id, user_id)`, `disabled_tool_ids: ARRAY(Integer) NOT NULL`. Already migrated
  (`backend/alembic/versions/b329d00a9ea6_adding_assistant_specific_user_.py`).
- DB layer `backend/onyx/db/user_preferences.py` (`get_all_user_assistant_specific_configs:375`,
  `update_assistant_preferences:387` upsert).
- Endpoints (`backend/onyx/server/manage/users.py`), both `BASIC_ACCESS`:
  - `GET /user/assistant/preferences` → `UserSpecificAssistantPreferences`
    (`= dict[int, {disabled_tool_ids: list[int]}]`).
  - `PATCH /user/assistant/{assistant_id}/preferences`, body
    `UserSpecificAssistantPreference {disabled_tool_ids: list[int]}` → 200, null body.

**No backend work.** The four send fields (`deep_research`, `allowed_tool_ids`, `forced_tool_id`,
`internal_search_filters`) already exist on `SendMessageRequest`
(`backend/onyx/server/query_and_chat/models.py:110,111,115,117`).

---

## Class / interface design

### New mobile contracts (`mobile/src/chat/`)

```ts
// mobile/src/chat/tools.ts — mirrors web/src/lib/tools/interfaces.ts (Tier-2 subset)
export interface ToolSnapshot {
  id: number;
  name: string;
  display_name: string;
  description: string;
  in_code_tool_id: string | null;   // matches SEARCH_TOOL_ID etc.
  mcp_server_id: number | null;      // MCP tools excluded from the list at Tier-2
  chat_selectable: boolean;          // visibility filter
}

// in-code tool identifiers — from web/src/app/app/components/tools/constants.ts
export const SEARCH_TOOL_ID = "SearchTool";
export const WEB_SEARCH_TOOL_ID = "WebSearchTool";
export const IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool";
export const FILE_READER_TOOL_ID = "FileReaderTool";       // always hidden from the list
// (PYTHON_TOOL_ID, OPEN_URL_TOOL_ID, CODING_AGENT_TOOL_ID for icon mapping)

export function isSearchTool(t: ToolSnapshot): boolean;      // in_code_tool_id === SEARCH_TOOL_ID
export function hasSearchToolsAvailable(tools: ToolSnapshot[]): boolean; // Search OR WebSearch present
export function displayableTools(tools: ToolSnapshot[]): ToolSnapshot[]; // chat_selectable, no MCP, no FileReader
export function computeAllowedToolIds(                       // agent tools − disabled
  tools: ToolSnapshot[], disabledToolIds: number[],
): number[] | null;                                         // null when nothing disabled (backend = allow all)
export const getIconForToolId: (inCodeToolId: string | null) => IconFunctionComponent; // mobile @/icons map
```

```ts
// mobile/src/chat/sources.ts — mirrors web ValidSources + source metadata (Tier-2 subset)
export type DocumentSource = string;   // snake_case wire values ("web","google_drive",…)
export interface SourceMeta { icon: IconFunctionComponent; displayName: string; }
export const SOURCE_META: Record<DocumentSource, SourceMeta>;   // fallback → generic globe/file
export function getSourceMeta(s: DocumentSource): SourceMeta;
export function buildInternalSearchFilters(                    // → { source_type } | null
  selectedSources: DocumentSource[],
): InternalSearchFilters | null;

// mobile/src/api/chat/stream.ts — new wire type
export interface InternalSearchFilters { source_type: DocumentSource[] | null; }
```

```ts
// The resolved bundle threaded into submit()
export interface ChatToolOptions {
  deepResearch: boolean;
  allowedToolIds: number[] | null;
  forcedToolId: number | null;
  internalSearchFilters: InternalSearchFilters | null;
}
```

### New primitives (`mobile/src/components/ui/`)

```ts
// select-button.tsx — mirrors Opal SelectButton (state-driven, no hover)
type SelectState = "empty" | "selected";
type SelectVariant = "select-light";          // only variant needed at Tier-2
interface SelectButtonProps {
  icon?: IconFunctionComponent;
  children?: string;                            // label
  state?: SelectState;                          // default "empty"
  variant?: SelectVariant;                      // default "select-light"
  foldable?: boolean;                           // label hidden when folded (icon-only)
  disabled?: boolean;
  onPress?: () => void;
  accessibilityLabel?: string;
}
// SELECT_COLORS: Record<SelectVariant, Record<SelectState, Record<"rest"|"active"|"disabled", {bg;fg;icon}>>>
// resolveSelectState(disabled, pressed) — parallels button.styles.ts resolveButtonState (no hover)

// switch.tsx — mirrors Opal Switch
interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  accessibilityLabel?: string;
}   // track 32×18 rounded-full; thumb 14×14; checked bg = action-link-05; reanimated thumb translate

// popover.tsx — anchored floating panel (Portal + reanimated + measureInWindow)
interface PopoverProps {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<View>;                   // the trigger, measured on open
  width?: number;                               // default 240 (web "lg" = w-60)
  children: ReactNode;
}   // opens UPWARD from a bottom-docked trigger; clamps on-screen; Keyboard.dismiss() on open
```

### State hooks (`mobile/src/hooks/`) + provider (`mobile/src/state/`)

```ts
useDeepResearchToggle({ chatSessionId: string | null; agentId: number | undefined }):
  { deepResearchEnabled: boolean; toggleDeepResearch: () => void }
  // EXACT web reset semantics: ref-guarded null→new-session preservation; reset on real session switch
  // and on agentId change. Port of web/src/hooks/useDeepResearchToggle.ts (55 lines).

useForcedTools({ agentId }): { forcedToolId: number | null; toggleForcedTool(id): void; clear(): void }
  // single-element force semantics; reset on agent change.

useAgentPreferences(): {
  disabledToolIdsFor(agentId): number[];
  setDisabledToolIds(agentId, ids: number[]): Promise<void>;   // optimistic + PATCH + invalidate
}   // TanStack Query GET /user/assistant/preferences keyed by serverUrl.

useConnectorSources(): { sources: DocumentSource[]; isLoading: boolean }
  // TanStack Query GET /manage/connector-status → BasicCCPairInfo[].map(c => c.source), deduped.
  // (federated /federated optional; behind EE — deferred, see notes.)

useSourceSelection({ agentId, availableSources, hasSearchTool }): {
  selectedSources: DocumentSource[]; isEnabled(s): boolean; toggle(s): void;
  enableAll(): void; disableAll(): void; initialized: boolean;
}   // ephemeral per-agent; self-initializes to all when availableSources first non-empty.

// state/ComposerToolsProvider.tsx — context aggregating the four resolved fields
useComposerTools(): {
  ...triggers/state for InputBar + ActionsPopover...
  resolveToolOptions(): ChatToolOptions;   // the object submit() consumes
}
```

---

## New files

| File | Responsibility |
|------|----------------|
| `mobile/src/components/ui/popover.tsx` | Anchored floating-panel primitive (measure trigger, Portal, upward, keyboard). |
| `mobile/src/components/ui/select-button.tsx` | Stateful pill primitive (empty/selected, foldable); backs deep-research + forced chips. |
| `mobile/src/components/ui/select-button.styles.ts` | `SELECT_COLORS` matrix + `resolveSelectState` (mirrors `button.styles.ts`). |
| `mobile/src/components/ui/switch.tsx` | Track+thumb toggle (reanimated); source rows. |
| `mobile/src/components/chat/ActionsPopover.tsx` | Tools menu: composes `Popover` + primary list + source sub-view; owns `open`/`subView`. |
| `mobile/src/components/chat/ActionLineItem.tsx` | One tool row: tap=force, trailing enable/disable + drill-in chevron. |
| `mobile/src/components/chat/SourceSwitchList.tsx` | Secondary view: back + Enable-All/Disable-All + `Switch` rows. |
| `mobile/src/components/chat/SourceIcon.tsx` | `DocumentSource` → logo/glyph (uses `SOURCE_META`). |
| `mobile/src/components/chat/ToolbarControls.tsx` | Renders the deep-research pill + forced-tool pills + Actions trigger in `InputBar`. |
| `mobile/src/chat/tools.ts` | `ToolSnapshot` type, tool-id constants, predicates, `getIconForToolId`. |
| `mobile/src/chat/sources.ts` | `DocumentSource`, `SOURCE_META`, `buildInternalSearchFilters`. |
| `mobile/src/hooks/useDeepResearchToggle.ts` | Ephemeral deep-research state (port of web hook). |
| `mobile/src/hooks/useForcedTools.ts` | Single-force state, reset on agent change. |
| `mobile/src/hooks/useAgentPreferences.ts` | GET/PATCH per-agent `disabled_tool_ids`. |
| `mobile/src/hooks/useConnectorSources.ts` | GET `/manage/connector-status` → source list. |
| `mobile/src/hooks/useSourceSelection.ts` | Ephemeral per-agent source selection + search coupling. |
| `mobile/src/api/chat/agentPreferences.ts` | `getAgentPreferences()` / `patchAgentPreferences(agentId, ids)`. |
| `mobile/src/api/chat/connectors.ts` | `getConnectorSources()` (connector-status fetch). |
| `mobile/src/state/ComposerToolsProvider.tsx` | Context hub aggregating the four fields; `resolveToolOptions()`. |
| `mobile/src/icons/{hourglass,globe,cpu,link,server,plug,unplug,slash}.tsx` | 8 new SVG icons (exact web path data in the plan). |

**Modified:**

| File | Change |
|------|--------|
| `mobile/src/chat/agents.ts` | Widen `MinimalAgent` with `tools: ToolSnapshot[]`, `knowledge_sources: DocumentSource[]`. |
| `mobile/src/api/settings.ts` | Add `deep_research_enabled?: boolean` to `WorkspaceSettings`. |
| `mobile/src/api/chat/stream.ts` | Add `allowed_tool_ids?`, `forced_tool_id?`, `internal_search_filters?` to `SendMessageBody`; add `InternalSearchFilters` type. |
| `mobile/src/hooks/useChatController.ts` | `submit(text, files?, onAccepted?, toolOptions?)`; replace hardcoded `deep_research: false` (`:296`) + populate three new fields (`:291`). |
| `mobile/src/components/chat/InputBar.tsx` | Render `<ToolbarControls>` in the left cluster (`:119-127`); accept agent + toolbar props. |
| `mobile/src/components/chat/ChatSurface.tsx` | Wrap in `ComposerToolsProvider`; pass `liveAgent.tools`; thread `resolveToolOptions()` into `sendWithAttachments`→`submit`. |
| `mobile/src/api/query-keys.ts` | Add `agentPreferences`, `connectorSources` keys (keyed by `serverUrl`). |

---

## File structure (tree)

```
mobile/src/
├── components/
│   ├── ui/
│   │   ├── popover.tsx                 (new)
│   │   ├── select-button.tsx           (new)
│   │   ├── select-button.styles.ts     (new)
│   │   ├── switch.tsx                  (new)
│   │   ├── button.tsx / button.styles.ts  (reference for SELECT_COLORS)
│   │   └── line-item-button.tsx        (reused — rightChildren slot already exists)
│   └── chat/
│       ├── ActionsPopover.tsx          (new)
│       ├── ActionLineItem.tsx          (new)
│       ├── SourceSwitchList.tsx        (new)
│       ├── SourceIcon.tsx              (new)
│       ├── ToolbarControls.tsx         (new)
│       ├── InputBar.tsx                (modified: left cluster renders ToolbarControls)
│       ├── ChatSurface.tsx             (modified: ComposerToolsProvider + thread options)
│       └── FilePickerSheet.tsx         (unchanged — separate paperclip sheet)
├── chat/
│   ├── tools.ts                        (new)
│   ├── sources.ts                      (new)
│   └── agents.ts                       (modified: widen MinimalAgent)
├── hooks/
│   ├── useDeepResearchToggle.ts        (new)
│   ├── useForcedTools.ts               (new)
│   ├── useAgentPreferences.ts          (new)
│   ├── useConnectorSources.ts          (new)
│   ├── useSourceSelection.ts           (new)
│   └── useChatController.ts            (modified: submit toolOptions + body build)
├── api/
│   ├── chat/
│   │   ├── agentPreferences.ts         (new)
│   │   ├── connectors.ts               (new)
│   │   └── stream.ts                   (modified: SendMessageBody + InternalSearchFilters)
│   ├── settings.ts                     (modified: deep_research_enabled)
│   └── query-keys.ts                   (modified)
├── state/
│   └── ComposerToolsProvider.tsx       (new)
└── icons/
    ├── hourglass.tsx  globe.tsx  cpu.tsx  link.tsx           (new)
    └── server.tsx  plug.tsx  unplug.tsx  slash.tsx           (new)
```

---

## What each file will contain

- **`popover.tsx`** — `Popover` component. On `open`, `anchorRef.current.measureInWindow((x,y,w,h)=>…)`
  → store the rect; render a full-screen `<Portal name="actions-popover">` containing a transparent
  outside-tap `Pressable` (closes) + an `Animated.View` panel positioned with
  `bottom = windowHeight - anchorY + GAP`, `left = clamp(anchorX, GUTTER, screenW - width - GUTTER)`,
  `maxHeight = anchorY - insets.top - GAP`, content in a `ScrollView`. `Keyboard.dismiss()` on open;
  reanimated `FadeIn` + slight `translateY`/`scale` from the bottom origin. Mirrors Opal
  `Popover.Content side="bottom" align="start" width="lg"` (`web/lib/opal/.../popover/components.tsx`),
  flipped upward (documented divergence).
- **`select-button.tsx` + `.styles.ts`** — pill built like `Button` but with a **stateful** matrix
  `SELECT_COLORS[variant][state][colorState]` (cells `{bg,fg,icon}`), `resolveSelectState(disabled,
  pressed)` (no hover). `select-light`: transparent bg in all states; `empty` fg=`text-04`/icon=`text-03`,
  `selected` fg/icon=`action-link-05` (from `stateful/styles.css:228-316`). `foldable` collapses the
  label to icon-only — since mobile has no `:hover`, implement as **conditional label render** driven
  by `state`/press (web's `foldable={!enabled}` = icon-only when off, label when on; the deep-research
  use needs exactly that, no hover-expand). Icon 16px (`iconWrapper` lg = 1rem).
- **`switch.tsx`** — `role="switch"` `Pressable` track (32×18, `rounded-full`), reanimated thumb
  (14×14) translating `2px`↔`17px`. Track bg `background-tint-03` → checked `action-link-05`; disabled
  variants per `switch/styles.css`. Controlled via `checked`/`onCheckedChange`.
- **`ActionsPopover.tsx`** — composes `Popover`; local `subView: {type:"sources"} | null` (mirrors web
  `secondaryView`). Primary body: `displayableTools(agent.tools).map(t => <ActionLineItem/>)`.
  Secondary: `<SourceSwitchList/>`. Reads/writes `useComposerTools`. In-place body swap with a slide
  (reanimated `LinearTransition`), same panel/anchor.
- **`ActionLineItem.tsx`** — one `LineItemButton`: `selected={forcedToolId===tool.id}`, `onPress`=force
  toggle (search tool not-yet-forced → open sources sub-view, mirroring web `ActionLineItem.tsx:98-108`).
  `rightChildren`: a trailing enable/disable control (always-visible `Switch` **or** an icon-`Button`
  with `SvgSlash` — mobile has no hover, so it can't be hover-revealed) + `EnabledCount` text for
  partial search sources + `SvgChevronRight` for the search drill-in. Disabled tools render dimmed
  (mobile `LineItemButton` lacks `strikethrough` — use `color="muted"` + a strike style, documented
  divergence).
- **`SourceSwitchList.tsx`** — back-chevron header (`SvgChevronLeft` `Button`) + Enable-All/Disable-All
  `LineItemButton` (`SvgPlug`/`SvgUnplug`) + per-source rows (`leading=<SourceIcon>`, label,
  `rightChildren=<Switch>`). Mirrors `SwitchList.tsx:61-119`. (Search box omitted — Tier-2 scope.)
- **`SourceIcon.tsx`** — `getSourceMeta(source).icon` via `Icon`; fallback glyph.
- **`ToolbarControls.tsx`** — renders, in order: the Actions trigger (`SvgSliders` `Button`, `ref` for
  the popover anchor) when `displayableTools(agent.tools).length>0`; the deep-research `SelectButton`
  (`SvgHourglass`, `state=on?"selected":"empty"`, `foldable={!on}`) when
  `deep_research_enabled && hasSearchToolsAvailable(agent.tools)`; one forced-tool `SelectButton`
  (`state="selected"`, tool icon+name, tap removes). Mounts `<ActionsPopover>`.
- **`tools.ts` / `sources.ts`** — as specified in Class design.
- **hooks** — as specified; `useAgentPreferences` optimistic-set then PATCH then invalidate;
  `useSourceSelection` ports the coupling (see notes).
- **`agentPreferences.ts` / `connectors.ts`** — thin `apiFetch` wrappers (paths bare — `getBaseUrl()`
  already appends `/api`): `apiFetch("/user/assistant/preferences")`,
  `apiFetch("/user/assistant/${id}/preferences", {method:"PATCH", body})`,
  `apiFetch("/manage/connector-status")`.
- **`ComposerToolsProvider.tsx`** — mounts the hooks (keyed `${sessionId}:${projectId}` + `agentId`),
  exposes the triggers/state and `resolveToolOptions()` = `{ deepResearch, allowedToolIds:
  computeAllowedToolIds(tools, disabled), forcedToolId, internalSearchFilters:
  buildInternalSearchFilters(selectedSources) }`.
- **8 icons** — exact `react-native-svg` ports of the web path data (viewBox `0 0 16 16` except
  `link` = `0 0 17 9` + `rotate(315deg)`), captured verbatim in `04-implementation-plan.md`.

---

## Integration points

- **`InputBar.tsx:119-148`** — the left cluster (`flex-row items-center gap-8`, currently paperclip
  only) gains `<ToolbarControls agent={…} tools={…}/>` after the paperclip. RIGHT cluster (send/stop)
  unchanged.
- **`ChatSurface.tsx`** — wraps its subtree in `<ComposerToolsProvider sessionId agentId
  agent={liveAgent}>`; `sendWithAttachments` calls `submit(text, descriptors, onAccepted,
  resolveToolOptions())`.
- **`useChatController.ts:228,291-298`** — `submit` gains a 4th `toolOptions?: ChatToolOptions` arg;
  the body literal sets `deep_research: toolOptions?.deepResearch ?? false`, `allowed_tool_ids`,
  `forced_tool_id`, `internal_search_filters`. `runChatStream` forwards `body` unchanged.
- **`stream.ts`** — `SendMessageBody` widened; JSON serialized as-is.
- **`useAgents()` / `useLiveAgent`** — no change; `liveAgent.tools`/`knowledge_sources` resolve once
  `MinimalAgent` is widened (data already on the `/persona` wire,
  `backend/onyx/server/features/persona/models.py:202,212`).
- **`useWorkspaceSettings()`** — `deep_research_enabled` read from the existing `/settings` GET
  (`backend/onyx/server/settings/models.py:50`).
- **`app/_layout.tsx:71`** — existing `<PortalHost/>` hosts the popover; no change.
- **`@onyx-ai/shared`** — **not touched** in this feature. Contracts live natively in
  `mobile/src/chat/` (matching the standing "chat layer is native, not shared" decision and the
  `mobile/src/chat/contracts/projects.ts` precedent). Shared extraction deferred to a future
  proven-reuse moment.

---

## Important notes before implementation

- **Anchored popover on a keyboard-adjacent bottom bar is the #1 risk.** Open upward
  (`bottom`-anchored math), `Keyboard.dismiss()` on open, clamp `left`/`width` to the screen, cap
  `maxHeight` + scroll. Re-measure on `keyboardWillShow/Hide` and on rotation. This is an on-device
  gate — the agent can't verify it; the owner must run a dev build. Fallback if anchored proves
  unstable on device: render the same `ActionsPopover` content through the `FilePickerSheet`
  bottom-sheet shell (swap only the container) — content is renderer-agnostic.
- **`SELECT_COLORS` must be a fully-typed literal matrix** like `BUTTON_COLORS`
  (`button.styles.ts:30-189`) — no computed keys — and use only NativeWind semantic token classes
  (`bg-*`, `text-*`). Mobile has **no hover**, so collapse the web hover cells; keep `icon` distinct
  from `fg` (web sets them separately).
- **`foldable` = state-driven, not hover-driven.** Web's `Interactive.Foldable` is a CSS
  `:hover`-triggered grid animation. On mobile, render the label only when the pill is expanded
  (`state==="selected"` for deep-research). Don't attempt a hover-expand.
- **No-hover enable/disable.** Web reveals `SvgSlash` on row hover. Decide one mobile affordance (a
  persistent trailing `Switch` on the tool row, or a persistent `SvgSlash` icon-`Button`) and apply
  it consistently. Port web's guard: **disabling a currently-forced tool clears the force**
  (`ActionLineItem.tsx:98-108`). Recommend a trailing `Switch` for consistency with the source rows.
- **Search-tool ↔ sources coupling — port the guards exactly or it render-loops.** From
  `ActionsPopover/index.tsx`: the reconcile effect is gated by `if (searchToolId===null ||
  !sourcesInitialized) return;` (`:742-759`) and only toggles when inconsistent. Forced tools are a
  single-element set (`:299-307`). Enabling a source auto-pins search; disabling the last source
  unpins it (`:365-396`); `previouslyEnabledSourcesRef` (a plain ref) restores sources when search is
  re-enabled (`:790-810`). Mirror the `sourcesInitialized`-equivalent guard and keep the "only toggle
  if different" idempotency (`setSearchToolEnabled`, `:762-770`). **Ship source→filter selection
  first, add the coupling as an isolated, jest-tested step.**
- **`useDeepResearchToggle` null→new-session preservation.** Replicate the ref guard exactly: reset to
  false only when `previousId !== null && previousId !== chatSessionId`; **always** reset on `agentId`
  change. A naive `[chatSessionId]` reset would drop the flag on the null→new-session transition
  mid-send. (`web/src/hooks/useDeepResearchToggle.ts:31-44`.)
- **`allowed_tool_ids`: send the computed enabled list, never a bare `[]`.** `computeAllowedToolIds`
  returns `null` when nothing is disabled (backend treats `null` = allow all); sending `[]` would
  disable everything. Match web's `enabledToolIds` semantics.
- **Default agent (id 0) sources.** `knowledge_sources` is empty for id 0; web treats it as "all
  accessible" using the connector list. Mobile `useConnectorSources` (GET `/manage/connector-status`,
  any chat-accessible user) supplies that list; non-default agents use `agent.knowledge_sources`,
  falling back to all if empty but a search tool is present (`ActionsPopover/index.tsx:199-210`).
  **Federated connectors** (`GET /federated`, EE) are deferred — a documented Tier-2 gap for
  federated-only sources.
- **`disabled_tool_ids` is shared with web.** A tool disabled on mobile PATCHes the same per-user
  per-agent record web reads — intentional cross-client sync. PATCH sends the **full** array
  (backend field is required). Optimistic update then invalidate; guard rapid-toggle races.
- **PII / cache.** `connectorSources` and `agentPreferences` are not chat content; safe to persist in
  the MMKV Query cache. Do **not** persist `selectedSources`/`forcedToolId`/`deepResearch` (ephemeral,
  live in provider state, never in Query).
- **`internal_search_filters` minimal shape.** Send `{ source_type: [...] }` only; all other
  `BaseFilters` fields default null on the backend (`search/models.py:101-121`). Values are the
  snake_case `DocumentSource` strings.
- **`FILE_READER_TOOL_ID` and MCP tools are always excluded** from the actions list
  (`displayableTools`); MCP/OAuth rows, the action search box, and the admin "More Actions" link are
  out of scope.
- **Testing hooks.** `tools.ts`/`sources.ts` are pure → jest unit tests (`computeAllowedToolIds` null
  vs list, `hasSearchToolsAvailable`, `displayableTools` filtering, `buildInternalSearchFilters`).
  `useDeepResearchToggle` reset matrix and the source-coupling reducer are the other high-value unit
  targets. Import leaf components directly in tests (reanimated barrels crash jest — see
  `mobile/CLAUDE.md`).
