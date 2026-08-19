> Status: active · Task: input-bar-controls · Approach: B — Web-Parity-First

# Mobile Input-Bar Controls (ActionsPopover + Deep-Research Toggle) — High-Level Design

## What it does

Adds two controls to the mobile chat composer, mirroring the web app: a **deep-research toggle**
(a pill that tells the model to do a thorough, multi-step search before answering) and an
**Actions menu** (a popover where the user picks which tools the agent may use, forces one specific
tool, and chooses which knowledge sources to search). Today the mobile composer only lets you type,
attach files, and send — these controls unlock the same tool/search control that web users already
have.

## How it works (end-to-end walkthrough)

When a chat screen is open, the composer already knows which **agent** is active (the "live agent").
Every agent that comes back from the server already carries the list of **tools** it can use and the
**knowledge sources** it can search — that data is already on the wire today, the mobile app just
wasn't reading it. So the moment we teach the mobile agent type to expose those two fields, the
composer has everything it needs with no extra network calls.

The composer's toolbar row gains, next to the existing paperclip:

1. A **deep-research pill** — but only when the workspace has deep research turned on *and* the
   current agent actually has a search tool. Tapping it flips an on/off value that lives in memory
   for the current conversation.
2. An **Actions trigger** (a sliders icon) — shown only when the agent has at least one selectable
   tool. Tapping it opens a small floating panel anchored just above the trigger.

Inside the Actions panel, each **tool** the agent has is a row. Tapping a row **forces** that tool
(the model must use it this turn) and highlights the row; tapping it again clears the force. A
separate toggle on the same row **enables or disables** that tool — a disabled tool is removed from
the set the agent is allowed to use. The search tool's row has a chevron that drills into a second
**sources** view: a back button, an "Enable All / Disable All" row, and one switch per knowledge
source. Turning sources on and off is coupled to the search tool the way web does it — turning a
source on makes sure search is active; turning the last one off releases it.

When the user hits **send**, the composer gathers four values and adds them to the message request
that already goes to the backend: `deep_research` (the toggle), `forced_tool_id` (the forced tool),
`allowed_tool_ids` (all the agent's tools minus the disabled ones), and `internal_search_filters`
(the chosen sources). The backend has always accepted these fields; mobile simply wasn't sending
them. The rest of the streaming path is unchanged.

Two of these values are **remembered differently**, matching web exactly: the enable/disable choice
per tool is **saved on the server per agent** (so it survives app restarts and stays in sync with
web), while the forced tool, the sources, and the deep-research toggle are **ephemeral** — they
reset when you switch agents or open a different conversation.

## Component interaction

```
                        GET /persona  ──► agent.tools[], agent.knowledge_sources[]
                                              │  (already on the wire; just widen the type)
                                              ▼
  ┌──────────────────────────── ChatSurface (composer host) ────────────────────────────┐
  │  useLiveAgent → selectedAgent          useWorkspaceSettings → deep_research_enabled   │
  │                                                                                       │
  │  ComposerToolsProvider  (state hub, keyed by session+agent)                           │
  │    ├─ useDeepResearchToggle   → deepResearchEnabled           (ephemeral)             │
  │    ├─ useForcedTools          → forcedToolId                  (ephemeral)             │
  │    ├─ useAgentPreferences     → disabledToolIds  ◄──► GET/PATCH /…/agent-preferences  │
  │    └─ useSourceSelection      → selectedSources              (ephemeral)             │
  │                         │ resolves →  { deep_research, allowed_tool_ids,              │
  │                         │              forced_tool_id, internal_search_filters }      │
  │                         ▼                                                             │
  │            ┌──────────  InputBar (toolbar row)  ──────────┐                           │
  │            │  [paperclip] [Actions ▸] [DeepResearch pill] │                           │
  │            │              [forced-tool pills…]  … [send]  │                           │
  │            └───────────────────┬───────────────────────────┘                          │
  │                                │ opens                                                │
  │                                ▼                                                       │
  │         ActionsPopover  ── anchored via Popover primitive ──► <PortalHost/>            │
  │           ├─ primary: ActionLineItem rows (force + enable/disable + chevron)           │
  │           └─ secondary: SourceSwitchList (back + Enable-All + Switch rows)             │
  └──────────────────────────────────┬────────────────────────────────────────────────────┘
                                      │ send
                                      ▼
                       useChatController.submit(text, files, onAccepted, toolOptions)
                                      │ builds SendMessageBody (+4 fields)
                                      ▼
                       runChatStream → streamChatMessage → POST /chat/send-chat-message
```

New primitives (`Popover`, `SelectButton`, `Switch`) sit under `mobile/src/components/ui/` and are
reused by these chat components.

## Key components

- **`Popover`** — anchored floating-panel primitive: measures the trigger, renders through a Portal,
  opens upward, clamps on-screen, handles the keyboard. (new, `components/ui/`)
- **`SelectButton`** — stateful pill (empty/selected, foldable to icon-only); backs the deep-research
  toggle **and** the forced-tool chips. (new, `components/ui/`)
- **`Switch`** — track+thumb toggle for the source rows. (new, `components/ui/`)
- **`ActionsPopover`** — the tools menu: composes `Popover` + the primary action list + the source
  sub-view. (new, `components/chat/`)
- **`ActionLineItem`** — one tool row (force-on-tap + enable/disable + drill-in chevron). (new)
- **`SourceSwitchList`** — the secondary sources view (back + Enable-All/Disable-All + `Switch` rows).
  (new)
- **`ComposerToolsProvider`** — the state hub that aggregates the four send-body values for the
  current conversation. (new, `state/`)
- **`useDeepResearchToggle` / `useForcedTools` / `useAgentPreferences` / `useSourceSelection`** — the
  state hooks (three ephemeral, one server-persisted). (new, `hooks/`)
- **`tools.ts` / `sources.ts`** — the `ToolSnapshot` type, tool-id constants, `getIconForAction`,
  `hasSearchToolsAvailable`, `computeAllowedToolIds`, `buildInternalSearchFilters`. (new, `chat/`)
- **`InputBar`** — renders the new controls in its left cluster. (modified)
- **`ChatSurface`** — wraps `ComposerToolsProvider`, feeds the agent's tools in, threads the resolved
  options into send. (modified)
- **`useChatController` / `stream.ts` / `agents.ts` / `settings.ts`** — widen the send body + the
  agent + settings types; drop the hardcoded `deep_research: false`. (modified)

## End-to-end scenario

1. User opens a chat with an agent that has Search, Web Search, and Image Generation tools, and the
   workspace has deep research enabled.
2. The composer shows the paperclip, a **sliders "Actions" button**, and a folded **hourglass**
   (deep-research) pill.
3. User taps **Actions** → a panel pops up above the button. The keyboard dismisses so the panel
   isn't clipped.
4. User taps the **Image Generation** row → it highlights (forced). User taps the enable/disable
   toggle on **Web Search** → Web Search is now disabled.
5. User taps the chevron on **Search** → the panel slides to the **sources** view. User turns off two
   connectors, leaving three on, and taps back.
6. User taps the **hourglass** pill → it expands to "Deep Research" and highlights.
7. User types a question and taps **send**. The request now carries
   `deep_research: true`, `forced_tool_id: <image-gen id>`,
   `allowed_tool_ids: [<all tools except Web Search>]`, and
   `internal_search_filters: { source_type: [<the three kept connectors>] }`.
8. The enable/disable choice (Web Search off) is saved to the server for this agent; next time the
   user opens this agent, Web Search is still disabled. The forced tool, sources, and deep-research
   pill reset.

## Sequence of key operations

1. `GET /persona` returns agents with `tools` + `knowledge_sources` (already happening; type widened).
2. `ChatSurface` resolves the live agent + workspace settings; `ComposerToolsProvider` mounts the
   four state hooks and fetches per-agent `disabled_tool_ids`.
3. `InputBar` conditionally renders the deep-research pill and Actions trigger from gating predicates.
4. User opens `ActionsPopover`; `Popover` measures the trigger and positions the panel.
5. User forces/enables/disables tools and picks sources; state updates flow into the provider; the
   enable/disable change PATCHes the server.
6. On send, the provider resolves the four fields; `useChatController.submit` writes them into
   `SendMessageBody`; `runChatStream` posts unchanged.
7. On agent/session change, ephemeral state resets; server-persisted `disabled_tool_ids` reloads.

## Key decisions & why

- **Anchored popover, not a bottom sheet (the web-parity call).** Web's control is a small panel
  pinned to its trigger with a foldable-pill row and an in-place drill-in; a full-width sheet would
  lose that relationship and make two adjacent toolbar buttons open different overlay idioms. We
  build a real anchored `Popover` on the same Portal + reanimated stack the sidebar already proves.
  Because the bar is bottom-docked above the keyboard, the panel opens **upward** and dismisses the
  keyboard on open — the one documented, platform-driven divergence from Radix's literal
  `side="bottom"`.
- **No new API for the tool/source catalog.** `MinimalPersonaSnapshot` already returns `tools` +
  `knowledge_sources`; we widen the mobile type instead of adding a fetch. (Verified:
  `backend/onyx/server/features/persona/models.py:202,212`.)
- **Server-persist `disabled_tool_ids` per agent; keep the rest ephemeral.** This matches web exactly
  (web persists via PATCH, resets forced-tool/deep-research per session) so the two clients stay in
  sync and the behavior is predictable. It also adds the mobile app's first agent-preferences write
  path.
- **Port three real primitives (`SelectButton`, `Switch`, `Popover`).** They don't exist on mobile
  yet, are needed for faithful look, and become reusable infrastructure for every future toolbar/menu
  port — done pixel/behavior-exact via `port-web-component-to-mobile`.

## What existing behavior changes

- Nothing regresses for existing users: the four fields are additive and optional; `deep_research`
  moves from a hardcoded `false` to the toggle's value (defaulting to `false` when the pill isn't
  shown or is off). No backend change.
- The composer's left cluster gains up to two new controls (shown only when their gates pass), so
  agents with no tools / workspaces with deep research off see no visible change.
- A new per-agent preference (`disabled_tool_ids`) starts being written from mobile — shared with the
  same web preference, so a tool disabled on mobile is disabled on web for that agent, and vice
  versa.
