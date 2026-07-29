# Mobile Chat 9a — Citations & Cited Sources

> Status: active — spec complete, ready for execution.

Sub-phase 9a of the deferred rich-chat work in `../05-pr-roadmap.md` (the parent mobile-chat
roadmap). Ports web's chat citations + cited-sources experience to the React Native app.

## Artifacts

1. [01-research.md](01-research.md) — requirement, clarifications, codebase + backend + web +
   industry findings, the three approaches, and the chosen one (C + A's inline simplification).
2. [02-high-level-design.md](02-high-level-design.md) — end-to-end walkthrough, component
   interaction, key decisions.
3. [03-detailed-design.md](03-detailed-design.md) — interfaces, new files, file tree, per-file
   contents, integration points, implementation notes.
4. [04-implementation-plan.md](04-implementation-plan.md) — CLAUDE.md-format plan + the appended
   plan-challenge results.
5. [05-pr-roadmap.md](05-pr-roadmap.md) — the single-PR delivery plan.

## One-line summary

Inline `[N]` markers become styled tappable links (open in the in-app browser) and a "Sources"
button + bottom sheet lists cited/found documents — built on a small reusable packet-processing +
source-UI foundation that PR 9b (agent timeline) extends. No backend/DB changes.
