# Mobile Chat Port — Spec Index

> Status: active · Task: mobile-chat · Approach: **C — Hybrid Seams**

Port the Onyx web chat experience to the React Native + Expo mobile app, delivered as independently-mergeable phases. Backend is unchanged. Pre-production (no backwards-compat / feature flags).

## Artifacts

1. [01-research.md](01-research.md) — requirement, locked clarifications, codebase scan (exact paths), industry best practices (sourced), 3 approaches + the chosen one.
2. [02-high-level-design.md](02-high-level-design.md) — plain-language end-to-end flow, component-interaction diagram, key decisions.
3. [03-detailed-design.md](03-detailed-design.md) — client data model (no DB change), shared-contract inventory, new files, file tree, renderer-registry foundation, pre-impl notes.
4. [04-implementation-plan.md](04-implementation-plan.md) — CLAUDE.md-format plan + appended **Plan Challenge** results (all checks pass; claims web-verified).
5. [05-pr-roadmap.md](05-pr-roadmap.md) — the delivery sequence: PR 0 (spikes) → 1 (shell) → 2 (**mobile-native chat data layer**: parser + contracts + tree + history) → 3 (**core chat** + renderer-dispatch foundation) → 4 (resume) · 5 (agents) · 6→7→8 (projects → files → attachments) · 9a–9e (rich-chat). Each PR has a **"Before you start (grill on)"** checklist.

> **Decision (2026-06-26, revised): no shared chat code.** The chat pure layer — NDJSON parser, message tree, `processRawChatHistory`, and all chat/streaming/file contracts — is written **natively in mobile** (PR 2), with web keeping its own existing copies. **Nothing chat-related enters `@onyx-ai/shared`.** We considered sharing the whole pure layer, then just the ~40-line parser, then dropped even that — the shared-package machinery (util + web re-point + jest mapper + dist coupling) is more moving parts than the ~200 lines of duplication it removes. Pre-production the backend protocol is stable, so drift risk is low and cheap to re-extract later if it bites. **Web is untouched by the mobile chat port.** Full rationale in the **PR 2** section of `05-pr-roadmap.md`.

## How to execute

Each PR is its own session. **Before coding a PR: open its entry in `05-pr-roadmap.md`, run the "Before you start (grill on)" checklist with the owner, re-read the cited web/mobile files, then implement.** The deep per-slice detail is produced in that session — this spec is deliberately high-level so it doesn't go stale.

**Web-parity is required for every component (PR 4 onward).** Every mobile component/screen must match its web counterpart as closely as the platform allows; reuse the parity primitives (`Text`, `Button`, …) first, check existing `components/*` before building, **ask the owner before porting a missing primitive** (don't hand-roll a divergent one), and each PR must document what differs from web and why. Full principle in the **WEB-PARITY PRINCIPLE** callout in `05-pr-roadmap.md`. (Sidebar parity is owned separately.)

**Hard gate before PR 3 (two-step):** the `expo/fetch` streaming spike is **DONE — PASS** (`getReader()` works on the iOS sim; recorded in `05-pr-roadmap.md`). The `react-native-streamdown` build/render check on RN 0.85 was **deferred to PR 3 pre-work** and is **still outstanding** — it must pass before PR 3 locks the markdown component (fallback `react-native-marked`).

## Locked scope

Core chat (send → stream → markdown → sessions/history) · agent **selection** only · projects (select + chat-within + file management; **no** project CRUD) · input-bar attachments (documents + photo library; **no** camera). Deferred to PR 9: citations, agentic timeline, regenerate/edit/feedback, follow-ups, image-gen.
