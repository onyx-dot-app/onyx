# Mobile Chat 9b — Agentic Reasoning Timeline

> Status: **active** — feature-flow complete (all 5 gated artifacts + plan-challenge). Ready to execute PR-by-PR.

Sub-phase 9b of the deferred rich-chat work in `../05-pr-roadmap.md` (the parent mobile-chat roadmap). A
**faithful 1:1 port of web's agent timeline shell** (`web/src/app/app/message/messageComponents/**`) to the React
Native app, wiring **only the reasoning renderer**. Approach **C — Faithful Shell First** (owner: "match web, no
refactor later, want everything"). Every tool renderer (search/fetch/python/custom-tool/deep-research/memory) and
9c–9e is an immediate follow-up PR on the **zero-refactor seam** this phase builds. Builds on the 9a foundation
(`../9a-citations/`, shipped #13025). No backend/DB changes.

## Artifacts

1. [01-research.md](01-research.md) — requirement, locked scope, codebase + backend + web + industry findings, the
   three approaches, and the chosen one (C).
2. [02-high-level-design.md](02-high-level-design.md) — end-to-end flow, component interaction diagram, key decisions.
3. [03-detailed-design.md](03-detailed-design.md) — exact contracts, new files, file tree, per-file responsibilities,
   integration points, the two ref-restructures, the documented divergences.
4. [04-implementation-plan.md](04-implementation-plan.md) — CLAUDE.md-format plan + appended plan-challenge results
   (all six pass; web-verified).
5. [05-pr-roadmap.md](05-pr-roadmap.md) — the 7-PR delivery sequence (9b.1 engine → … → 9b.7 composition/device gate).

Supporting reference (gitignored): `.context/pr9b-deepread/*.md` — verbatim web timeline contracts extracted for
the faithful port.

## One-line summary

Port web's agent reasoning timeline shell to mobile 1:1 (grouping engine + `section_end` synthesis + pacing +
7-state machine + render-prop renderer contract + StepContainer/collapse), wiring only the reasoning renderer;
delivered as 7 layered PRs so the tool renderers drop in later with zero refactor. One accepted, platform-forced
divergence: the two ref-during-render hooks are restructured (behavior-preserving) to satisfy `react-hooks/refs`.
