# Mobile Input-Bar Controls (ActionsPopover + Deep-Research Toggle)

> Status: active · Task: input-bar-controls · Approach: B — Web-Parity-First

Port web's chat input-bar toolbar controls to the Onyx React Native mobile composer at **Tier-2
(Standard)** scope: a **deep-research toggle** and an **anchored ActionsPopover** (force-a-tool +
enable/disable tools + a source-selection sub-view). Out of scope: MCP servers/tools, OAuth re-auth,
the admin "More Actions" link, the action search box.

Feature-flow spec (read in order):

1. [01-research.md](01-research.md) — requirement, Tier-2 scope decision, verified codebase scan
   (both ends), popover industry analysis (bottom-sheet vs anchored), 3 approaches + the chosen one.
2. [02-high-level-design.md](02-high-level-design.md) — plain-language end-to-end flow, component
   interaction diagram, end-to-end scenario, key decisions.
3. [03-detailed-design.md](03-detailed-design.md) — no DB/backend changes (endpoints + fields already
   exist); interface design (types, primitives, hooks), new-files list, file tree, per-file contents,
   pre-implementation notes.
4. [04-implementation-plan.md](04-implementation-plan.md) — CLAUDE.md-format plan + the appended
   `plan-challenge` results (all six checks clear) + exact SVG path data for the 8 new icons.
5. [05-pr-roadmap.md](05-pr-roadmap.md) — 4 review-sized PRs (foundation → deep-research skeleton →
   ActionsPopover tools → sources + coupling) with scope, files, tests, and drift checkpoints.

**Load-bearing facts (verified):** the `/persona` payload already carries `tools` +
`knowledge_sources` (no new fetch for the catalog); the backend `SendMessageRequest` already accepts
all four fields; per-agent `disabled_tool_ids` already has a table + `GET`/`PATCH` endpoints. **No
backend work, no migration.**

**Owner-owed gate:** the anchored popover's keyboard/off-screen behavior needs an on-device dev build
(PR 3); fallback is the `FilePickerSheet` bottom-sheet shell.
