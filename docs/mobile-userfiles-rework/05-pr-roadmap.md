> Status: active · Task: mobile-userfiles-rework · Source plan: 04-implementation-plan.md

# Mobile file-upload module restructure — PR Roadmap

## Overview

**Single PR** (owner decision at GATE 3). The whole restructure ships together.

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 1 | `refactor(mobile): normalized userFileStore SSOT + composer draft context` | ~2000 | — | Approach C — a file-keyed `userFileStore` as the **single source of truth for every file record** (uploads, draft attachments, project files, recent/library): `filesById` + `projectFileIds` + `recentIds` + `hydrateProject`/`hydrateRecent` loaders, one reconcile reducer, epoch, atomic selectors + `ComposerDraftContext` ({text,fileIds}) + `useUpload` + a single `UploadReconciler` poll over all processing store files; Query is demoted to fetch-and-hydrate (never renders files); both lenses read id-refs from the store (`useComposerDraft` text+attachments, `useProjectFiles` via `projectFileIds`, recent picker via `recentIds`); BUG1/BUG2/BUG3 fixed; `BearerImage` rider; old `uploadStore` deleted. |

> Note (owner-acknowledged): ~2000 LOC is well above the ~500-700 review band, so the PR is **structured as four ordered commits** (below) that mirror the original phase boundaries — dependency-ordered, each independently green (`typecheck`+`lint`+`jest`), so it can be reviewed commit-by-commit. If review proves unwieldy, the commit boundaries are pre-cut split points.

## Commit & review policy (owner directive)

**Do NOT commit during implementation.** The agent implements all four commits' worth of changes and leaves them **unstaged/uncommitted in the working tree** for the owner to review first. Only **after the owner reviews** does anything get committed — and the owner directs how (the A→B→C→D commit split above is the suggested structure to apply *at that point*, not before). Same for any push/PR: nothing is pushed or a PR opened until the owner says so. Verification (`typecheck`/`lint`/`jest`) still runs during implementation; only the git commit/push steps wait for review.

## Sequence (internal commit order within the single PR)

```
Commit A — prep         : BearerImage rider · BUG2 fallback · UploadTransport seam + createUploadTask
Commit B — foundation   : userFileStore SSOT (engine + projectFileIds/recentIds + hydrateProject/hydrateRecent) + useUpload + a single UploadReconciler over ALL processing store files (dark; unit-tested)
Commit C — draft flow   : ComposerDraftProvider (context) + useComposerDraft (text+attachments) · submit(onAccepted) BUG1 · ChatSurface/InputBar/FileCard
Commit D — project flow : useProjectFiles + useRecentFiles READ from the store (projectFileIds / recentIds), hydrate on fetch, DROP the project Query hand-off, REMOVE any per-surface status poll · ProjectContextPanel · DELETE uploadStore
```
Each commit leaves the tree green; A→B→C→D is the safe build order (B needs A's transport; C and D need B's store; D deletes the old store last).

---

## PR 1 — `refactor(mobile): file-keyed composer/upload store + composer draft`

- **Goal:** Replace the two forked file layers with one normalized file-keyed store as the **single source of truth for every file record** (uploads, draft attachments, project files, recent/library) + hooks that read id-refs from it (core engine + composer-draft lens + project lens + recent picker), with Query demoted to fetch-and-hydrate loaders that never render files; persist the composer draft (text + attachments) across navigation, and fix the three P2 bugs — all in one PR, built as four ordered commits.

### Commit A — prep (no store dependency)
- **Scope:** `BearerImage` extraction (rider) collapsing `AttachmentImage`/`AgentImage`; BUG2 `DEFAULT_MAX_UPLOAD_MB=100` + `resolveMaxUploadMb` in `lib/files.ts`; `UploadTransport` seam (`api/files/transport.ts`) + `api/files/upload.ts` `createUploadTask` migration (behavior-preserving).
- **Green when:** `BearerImage` render test; `resolveMaxUploadMb` returns 100 on null/0; `uploadUserFile` via `createUploadTask` keeps non-2xx/JSON guards.

### Commit B — foundation (dark)
- **Scope:** `state/userFileStore.ts` — the SSOT engine (`filesById` (now holds **every** file record) / `tasksById`(target-tagged) / `progress` / `projectFileIds: Record<number,string[]>` / `recentIds: string[]` / `errorsByTarget` / `epochCounter` + `runtimeHandles`, `UserFileActions` incl. the one `reconcile` reducer plus `hydrateProject`/`hydrateRecent`/`registerExisting`, atomic selectors incl. `useTargetUploadIds` and `useFilesByIds` (filters missing ids), `subscribeWithSelector`); `hooks/useUpload.ts` (project upload appends the optimistic id to `projectFileIds` + refetches project-details — **no** Query hand-off); `components/chat/UploadReconciler.tsx` as the **single** poller over all `isServerProcessingStatus` files in `filesById` (project + draft + recent) + mount in `app/(app)/_layout.tsx`. Unconsumed by lenses yet.
- **Green when:** engine unit tests (reconcile temp→server + server-wins + match-by-temp_id-then-id, epoch no-op, `failTask` retryable, `removeFile` cancels, target selectors); `hydrateProject`/`hydrateRecent` upsert records and set `projectFileIds`/`recentIds`; `useFilesByIds` selectors resolve id-refs and drop missing ids; `useUpload` (size/transport/optimistic `projectFileIds` add + refetch, no hand-off); the reconciler polls **all** processing store files (poll + `AppState` resume + orphan-retry).

### Commit C — draft flow (walking skeleton)
- **Scope:** `components/chat/ComposerDraftProvider.tsx` (new React context: `Record<draftKey,{text,fileIds}>` via reducer + `setText`/`addFiles`/`removeFile`/`consume`/`consumeAttachments`; mounted above `ChatSurface` in `_layout.tsx`); `hooks/useComposerDraft.ts` (rename/rewrite of `useMessageAttachments.ts`; sole draft-context consumer, composed with `userFileStore`; delete old local-state/keyRef/poll); `hooks/useChatController.ts` (drop `input`/`setInput`; `submit(text, files?, onAccepted?)`; BUG1 both faces); `components/chat/ChatSurface.tsx` (draft text; delete `setInput("")` effect; consume-on-accept, `consume` vs `consumeAttachments`); `InputBar.tsx`/`FileCard.tsx` (`useUploadProgress`; drop `progressById`; `React.memo` chip strip).
- **Green when:** draft (text+attachments) restores after a `draftKey` switch; a bailed `submit` keeps the draft; starter send keeps text/clears attachments; send-gating on `hasBlockingFiles`.

### Commit D — project flow + cleanup
- **Scope:** `hooks/useProjectFiles.ts` (rewrite: reads `projectFileIds[projectId]` → `useFilesByIds` from the SSOT store, prepends in-flight tasks from `useTargetUploadIds({project:id})`; **no** Query-rendered committed list; link/unlink update `projectFileIds` optimistically + refetch project-details to re-hydrate; **no** per-surface poll); `hooks/useRecentFiles.ts` + `lib/files.ts` (fetch `/user/files/recent` → `hydrateRecent`; the recent picker renders from `recentIds` in the store; **no** per-surface poll); `components/chat/ProjectContextPanel.tsx` (drop `progressById`); **delete** `state/uploadStore.ts` + `state/__tests__/uploadStore.test.ts`.
- **Green when:** project optimistic upload just **stays** in the store (its id appended to `projectFileIds`) and reconciles with no double-count; link/unlink update `projectFileIds` optimistically + refetch re-hydrates membership; recent picker renders from `recentIds`; the single `UploadReconciler` (not a per-surface poll) reconciles project + recent processing files; grep proves zero Query-rendered file lists and zero `uploadStore` importers before deletion.

### Files (whole PR)
| File | New/Modified/Deleted | Commit |
|------|----------------------|--------|
| `components/ui/BearerImage.tsx` (+ test) | new | A |
| `components/chat/AttachmentImage.tsx`, `components/avatars/AgentImage.tsx` | modified → wrappers | A |
| `lib/files.ts` (+ test) | modified | A |
| `api/files/transport.ts` | new | A |
| `api/files/upload.ts` (+ test) | modified | A |
| `state/userFileStore.ts` (+ test) | new (rewrite of uploadStore) | B |
| `hooks/useUpload.ts` (+ test) | new | B |
| `components/chat/UploadReconciler.tsx` (+ test) | new | B |
| `app/(app)/_layout.tsx` | modified | B |
| `components/chat/ComposerDraftProvider.tsx` (+ test) | new (React context) | C |
| `hooks/useComposerDraft.ts` (+ test) | new (rename) | C |
| `hooks/useChatController.ts` (+ test) | modified | C |
| `components/chat/ChatSurface.tsx`, `InputBar.tsx`, `FileCard.tsx` | modified | C |
| `app/(app)/_layout.tsx` | modified (mount `<ComposerDraftProvider>`) | C |
| `hooks/useProjectFiles.ts` (+ test) | modified (rewrite: reads `projectFileIds` from the SSOT store, no Query render) | D |
| `hooks/useRecentFiles.ts` (+ test) | modified (fetch `/recent` → `hydrateRecent`; picker reads `recentIds`) | D |
| `lib/files.ts` | modified (recent fetch hydrates the store, never renders) | D |
| `components/chat/ProjectContextPanel.tsx` | modified | D |
| `state/uploadStore.ts` (+ test) | deleted | D |

- **Est. size:** ~2000 LOC (owner-chosen single PR; four internal commits are the pre-cut split points).
- **Depends on:** —
- **Feature-flag state:** N/A — old and new paths coexist until Commit D removes the old store; every commit leaves `main` releasable.
- **Tests on merge:** jest (unit/component) — the store is the center of gravity; see each commit's "green when". Gate: `bun run typecheck && bun run lint && bunx jest`.
- **Drift checkpoint (consolidated, confirm before starting):**
  1. `createUploadTask`/`sessionType` exists in the installed `expo-file-system@~56.0.8` (native dep — verify, not assumed).
  2. `03` store shape holds — esp. `reconcile` match order (temp_id then id) and the epoch guard as the sole late-write fix.
  3. The persist-across-navigation UX (option b: text + attachments) still stands; the exact `onAccepted` insertion point in `submit` (after the active-run guard, before `createChatSession`).
  4. IME/cursor behavior of the store-controlled `TextInput` on device (fallback = local mirror).
  5. No project Query hand-off remains: verify the optimistic id is appended to `projectFileIds` and a project-details refetch re-hydrates membership cleanly (no double-count); grep-confirm **zero Query-rendered file lists** remain and zero `uploadStore`/`useProjectUploads` importers before deletion.
  6. Re-confirm the SSOT premise: `GET /user/files/recent` returns the **full library** (no `LIMIT`, no time-bound `WHERE`; excludes only FAILED/DELETING; `onyx/server/manage/users.py:1305`), and a project file is a subset **by id** (`Project__UserFile` join, `onyx/db/models.py:5069`; `UserFileSnapshot.project_id` hardcoded `None`, `projects/models.py:38`) — so id-refs (`projectFileIds`/`recentIds`) reliably resolve against `filesById`.
  7. **Owner HARD GATE:** native rebuild (`expo prebuild --clean` + `run:ios`/`run:android`) — pick→upload→progress→navigate-with-draft→return→send, minimize/return reconcile, bearer thumbnails.
