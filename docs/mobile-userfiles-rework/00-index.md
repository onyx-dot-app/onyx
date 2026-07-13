# Mobile file-upload module restructure — Spec Index

> Status: active — design locked, sliced into one owner-chosen PR. Execution (writing code) is a separate step.
> Approach: **C — Normalized file cache** (one store is the single source of truth for every file record; TanStack Query fetches-and-hydrates only, never renders). Revised from Approach B after backend + web research confirmed `/user/files/recent` is the full library, project files are a subset of it by id, and web's multi-list `ProjectsContext` is the anti-pattern to replace.

| # | Artifact | What's in it |
|---|----------|--------------|
| 01 | [Research](01-research.md) | Requirement, store-vs-context rationale, codebase scan, web reference (`ProjectsContext`), industry best-practices, 3 approaches + chosen. |
| 02 | [High-Level Design](02-high-level-design.md) | Plain-language end-to-end walkthrough, component diagram, key decisions, unified composer draft (text + attachments). |
| 03 | [Detailed Design](03-detailed-design.md) | Engine-store + draft-context shapes (per-field rationale), `UserFileActions` + draft actions, atomic selectors, `UploadTransport` seam, hooks, new-files list, file tree, per-file contents, verified backend facts. |
| 04 | [Implementation Plan](04-implementation-plan.md) | CLAUDE.md-format plan (Issues / Notes / Strategy / Tests) + appended `plan-challenge` results (all 6 checks pass; proper fix). |
| 05 | [PR Roadmap](05-pr-roadmap.md) | Single PR (owner choice) built as 4 ordered commits (prep → foundation → draft flow → project flow), file table, tests, drift checkpoints, **commit-only-after-owner-review policy**. |

## The rework in one line
Replace the two forked mobile file layers (project-keyed store + per-message local draft) with **one normalized file cache** — a file-keyed **`userFileStore`** zustand engine that is the **single source of truth for every file record** (uploads, draft attachments, project files, recent/library), with project/draft/recent holding only **id-references** and TanStack Query demoted to a **fetch-and-hydrate loader** (never rendered for files). The per-conversation composer draft (text + attachment id-refs) lives in a small **`ComposerDraftContext`** (synchronous UI state, behind `useComposerDraft`). Plus a core `useUpload` engine hook and thin lens hooks (`useComposerDraft`, `useProjectFiles`, the recent-files picker), fixing the 3 deferred P2 bugs structurally and keeping a future background-upload a bounded add.

## Execution note
Per owner directive (05 → Commit & review policy): implement everything and **leave it uncommitted for review**; commit/push only after the owner reviews and directs.
