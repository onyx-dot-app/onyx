# Mobile Chat Port — Spec Index

> Status: active · Task: mobile-chat · Approach: **C — Hybrid Seams**

Port the Onyx web chat experience to the React Native + Expo mobile app, delivered as independently-mergeable phases. Backend is unchanged. Pre-production (no backwards-compat / feature flags).

## Artifacts

1. [01-research.md](01-research.md) — requirement, locked clarifications, codebase scan (exact paths), industry best practices (sourced), 3 approaches + the chosen one.
2. [02-high-level-design.md](02-high-level-design.md) — plain-language end-to-end flow, component-interaction diagram, key decisions.
3. [03-detailed-design.md](03-detailed-design.md) — client data model (no DB change), shared-contract inventory, new files, file tree, renderer-registry foundation, pre-impl notes.
4. [04-implementation-plan.md](04-implementation-plan.md) — CLAUDE.md-format plan + appended **Plan Challenge** results (all checks pass; claims web-verified).
5. [05-pr-roadmap.md](05-pr-roadmap.md) — the delivery sequence: PR 0 (spikes) → 1 (shell) → 2 (shared parser) → 3 (**core chat** + renderer-dispatch foundation) → 4 (resume) · 5 (agents) · 6→7→8 (projects → files → attachments) · 9a–9e (rich-chat). Each PR has a **"Before you start (grill on)"** checklist.

## How to execute

Each PR is its own session. **Before coding a PR: open its entry in `05-pr-roadmap.md`, run the "Before you start (grill on)" checklist with the owner, re-read the cited web/mobile files, then implement.** The deep per-slice detail is produced in that session — this spec is deliberately high-level so it doesn't go stale.

**Hard gate:** PR 0's two spikes (`expo/fetch` streaming on device; `react-native-streamdown` on RN 0.85, fallback `react-native-marked`) must pass before PR 3.

## Locked scope

Core chat (send → stream → markdown → sessions/history) · agent **selection** only · projects (select + chat-within + file management; **no** project CRUD) · input-bar attachments (documents + photo library; **no** camera). Deferred to PR 9: citations, agentic timeline, regenerate/edit/feedback, follow-ups, image-gen.
