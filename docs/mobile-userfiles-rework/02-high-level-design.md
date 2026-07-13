> Status: active · Task: mobile-userfiles-rework · Approach: C — Normalized file cache (single store SSOT; Query fetches-and-hydrates, never renders)

# Mobile file-upload module restructure — High-Level Design

## What it does

Replaces the mobile app's two forked file layers (a project-keyed zustand store + a per-message local-state draft) with **one normalized file cache + a draft context, split by concern** and a set of thin hooks. The **`userFileStore`** zustand store is the **single source of truth for every file record** — uploads, draft attachments, project files, *and* recent/library files all live in one id-keyed `filesById` map; projects, the recent picker, and the composer draft hold **only id-references** that resolve against it. A **`ComposerDraftContext`** React context still owns the per-conversation composer draft (= text + file references, synchronous UI state), fronted by a core engine hook plus thin lenses (the composer draft, project files, recent files). A file becomes the identity in the store; "attached to this message", "linked to project 5", and "in your recent list" become references on top. **TanStack Query is demoted to a fetch-and-hydrate loader**: it still does the fetch mechanics (retry, dedup, focus-refetch, lazy `enabled`), but its results *hydrate* the store on success and are **never rendered for files** — one source, several loaders, so the dual-source drift that sank the original Approach C is eliminated by the single rule "Query never renders files". The composer draft — **text *and* attachments together** — lives in its own context (mounted above the persistent `ChatSurface`), so navigating away and back restores the whole draft (today the message text is a single `useState` in `useChatController`, wiped on every conversation switch). The result: an upload survives navigation, the composer draft survives navigation, progress never re-renders the whole file list, the three deferred P2 bugs (plus the text-input's own copy of the clear-on-bailed-send bug) are fixed structurally, and a future background-upload feature is a bounded add rather than a rewrite.

## How it works (end-to-end walkthrough)

Everything is anchored by one fact about the app shell: the chat UI is a single `ChatSurface` overlay mounted once over the router stack (`app/(app)/_layout.tsx`); it **morphs** between "new chat", "chat N", and "project P" without ever remounting. So any state a file needs must live *outside* React — in a store — or it leaks across conversations (the reason PR 8 needed its `keyRef`/`resetKey` dance).

A store + a context, split by concern:

**`state/userFileStore.ts` — the normalized file cache + upload engine** (rewrite of `uploadStore.ts`), the single source of truth for every file record, holds:
- **`filesById`** — the canonical record for **every** file (upload, draft attachment, project file, recent/library file), keyed by a stable `clientId`. For an upload, `clientId` is the temp id assigned at pick time and it **never moves** — even after the server swaps in the real id, the record's *key* stays put; only the file's `id`/`file_id` fields fill in. For a hydrated server file (recent or project), `clientId` is the server id.
- **`projectFileIds`** — `Record<projectId, clientId[]>`, a project's committed membership as ordered id-references, hydrated from project-details. A project file is the *same* record in `filesById`; membership is just this association list.
- **`recentIds`** — `clientId[]`, the recent/library list as ordered id-references, hydrated from `/user/files/recent`.
- **`tasksById`** — a first-class **upload task** per in-flight upload (progress, a monotonic `epoch`, status, error, a cancel handle in a side table, and a `target` tag). Progress lives *here*, not on the file record, so a progress tick touches the task and never churns the file list.
- **`errorsByTarget`** — size/picker errors per upload target.

Hydrate actions `hydrateProject(projectId, files)` (upsert records + set `projectFileIds[projectId]`) and `hydrateRecent(files)` (upsert records + set `recentIds`) let the loaders write server truth into the store; `reconcile` (match by `temp_id` else id, server wins) is unchanged and now also runs from the unified poll for every surface; `registerExisting` stays (single recent-attach for a draft).

**`components/chat/ComposerDraftProvider.tsx` — the composer draft** (new React context, mounted above `ChatSurface`), holds:
- **`drafts[draftKey] → { text, fileIds }`** — the per-conversation composer draft: the message text *and* the attachment `clientId` **references** (never copies) into `userFileStore`. Written only from synchronous React actions (type/pick/remove/send). This is what makes text + attachments survive navigation and clear together on send.

Project uploads need **no** separate committed list — a project's members are `projectFileIds[id]` resolved against `filesById`, and the in-flight optimistic ones are *derived* from `userFileStore.tasksById` where `target = {project:id}` (their optimistic ids are also appended to `projectFileIds[id]`).

When you pick files, the core hook runs a size pre-check, inserts optimistic records + tasks, links them to the target (draft or project), and starts the upload through a **`UploadTransport` interface** — today a foreground implementation, later swappable for a background one without the store knowing. As bytes flow, `onProgress` updates the task. When the server responds, a **single `reconcile` reducer** merges the authoritative server record onto the optimistic one (matched by the echoed `temp_id`) and marks the task terminal. For a project upload the optimistic id was already appended to `projectFileIds[id]`; the upload record simply *stays* in the store, and a project-details refetch re-hydrates membership to confirm the server truth — there is **no hand-off, no invalidate-then-remove**. **The store is the single source of truth for every file; the loaders (upload, `/recent`, project-details, `/statuses`) fetch and *hydrate* it, and Query is never rendered for files** (that's the line we deliberately hold — one source, several loaders, so there is no second source of truth to drift).

Completion is never trusted to a live in-memory callback. A mounted `UploadReconciler` is the **single** poller for the whole app: it re-polls `/statuses` on a 3s loop for **every** file in `filesById` still in a server-processing status (project, draft, *and* recent alike) → `reconcile`, and — critically — fires an immediate re-poll whenever the app returns to the foreground (`AppState` "active"). There is no per-surface status poll and no Query status-patcher. So a file that finished server-side while the app was backgrounded reconciles the moment you return, wherever it lives. Every write into the store is guarded by the task's `epoch`: a late callback from a superseded run finds a bumped epoch and self-invalidates — no debounce, no stale error banner.

## Component interaction

```
 LOADERS (fetch → hydrate; never rendered for files)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  TanStack Query (fetch mechanics: retry / dedup / focus-refetch / enabled) │
 │   useRecentFiles  ──onSuccess──▶ hydrateRecent(files)                       │
 │   useProjectDetails ─onSuccess─▶ hydrateProject(id, files)  (non-file       │
 │                                   fields e.g. name/personas may render)     │
 │   useUpload/transport ─response▶ reconcile(user_files, epoch)               │
 │   UploadReconciler ──/statuses─▶ reconcile(...)                             │
 └───────────────────────────────┬────────────────────────────────────────────┘
                                  │ hydrate / reconcile (server wins)
                                  ▼
   ┌─────────────────────────────────────────┐   ┌──────────────────────────────────┐
   │  userFileStore (zustand — the SSOT)      │   │  ComposerDraftContext (the draft) │
   │  filesById:      clientId → FileRecord   │   │  drafts: draftKey → {text,fileIds}│
   │  projectFileIds: projectId → clientId[]  │   │  (React context, above ChatSurface)│
   │  recentIds:      clientId[]              │◀──┼── fileIds = refs into userFileStore│
   │  tasksById:      taskId → UploadTask      │   └──────────────────────────────────┘
   │                  (progress, epoch, target)│         references (clientId)
   │  errorsByTarget · reconcile · hydrate*    │
   └──▲──────────────▲───────────────▲─────────┘
      │ atomic/id     │ target-select │ useFilesByIds (resolve refs → records)
      │ selectors     │               │
 ┌────┴─────────┐ ┌───┴───────────┐ ┌─┴──────────────┐ ┌──────────────────┐
 │  useUpload   │ │useComposerDraft│ │ useProjectFiles │ │ recent picker    │
 │ (core engine)│ │ (draft lens —  │ │ projectFileIds[id]│ (recentIds →     │
 │ transport +  │ │ context+store) │ │  + in-flight tasks│  useFilesByIds)  │
 │ size (no     │ └──────┬─────────┘ └─────┬──────────┘ └──────────────────┘
 │  hand-off)   │        │                 │
 └────┬─────────┘    InputBar        ProjectContextPanel
      │
      │ single poller: AppState "active" + 3s poll over ALL processing
      │ files in filesById → /statuses → userFileStore.reconcile
 ┌────┴─────────────┐
 │ UploadReconciler │  (null component, mounted once in app/(app)/_layout.tsx)
 └──────────────────┘

 transport seam:  useUpload → UploadTransport (foreground now │ background later) → POST /user/projects/file/upload
 VIEWS read id-refs and resolve via useFilesByIds; Query is a loader, never rendered for files
```

## Key components

- **`state/userFileStore.ts`** — the normalized file cache + upload engine, **SSOT for every file record**: `filesById` + `projectFileIds` + `recentIds` + `tasksById` (target-tagged) + `errorsByTarget` + the `reconcile` reducer + `hydrateProject`/`hydrateRecent`/`registerExisting` + epoch. Context-agnostic. (rewrite of `uploadStore.ts`)
- **`components/chat/ComposerDraftProvider.tsx`** — the composer draft as a **React context**: `Record<draftKey, { text, fileIds }>` (fileIds = references into `userFileStore`). Pure synchronous UI state, mounted above `ChatSurface`; behind `useComposerDraft` so it can be promoted to a store later without touching components. (new)
- **`api/files/transport.ts`** — `UploadTransport` interface + `foregroundTransport` + `getUploadTransport`/`configureUploadTransport`; the seam a background impl drops into. (new)
- **`hooks/useUpload.ts`** — core engine over `userFileStore`: size pre-check, `beginUpload`, transport start, reconcile wiring, cancel/remove. A project upload appends the optimistic id to `projectFileIds` and refetches project-details to confirm server membership — **no invalidate + removeFile hand-off**. The only place upload logic lives. (new)
- **`components/chat/UploadReconciler.tsx`** — null component, the app's **single** poller: the 3s `/statuses` poll over **all** processing files in `filesById` (project + draft + recent) + the `AppState` foreground re-poll → `userFileStore.reconcile`. (new)
- **`hooks/useComposerDraft.ts`** — the **sole** `ComposerDraftContext` consumer; composes it with the store: `text`/`setText` (draft context; was `useChatController.input`) + the attachment surface (files via draft refs → engine records, minus `progressById`) + `consume`/`consumeAttachments`. (rename of `useMessageAttachments.ts`)
- **`hooks/useProjectFiles.ts`** — thin project-panel lens: reads `projectFileIds[projectId]` → `useFilesByIds`, prepends in-flight tasks; link/unlink update `projectFileIds` optimistically then refetch project-details (re-hydrate). **No Query-rendered committed list, no per-surface poll.** Same public shape. (rewrite)
- **`hooks/useRecentFiles.ts`** — recent/library loader: fetches `/user/files/recent`, `hydrateRecent`s the store; the recent picker reads `recentIds` → `useFilesByIds`. No per-surface poll (the single `UploadReconciler` covers recent too). (new)
- **`components/ui/BearerImage.tsx`** — shared authed-image primitive; `AttachmentImage` + `AgentImage` collapse onto it. (new, independent commit)
- **`lib/files.ts`** — adds `DEFAULT_MAX_UPLOAD_MB = 100` + `resolveMaxUploadMb` (BUG2's one home). (modified)
- **`hooks/useChatController.ts`** — drops `input`/`setInput`; `submit` takes explicit `text` + an `onAccepted?()` fired at the guaranteed-committed point (both faces of BUG1). (modified)
- **`components/chat/ChatSurface.tsx`** — composer text comes from the draft; the `setInput("")`-on-switch effect is deleted; the draft is consumed only on accept. (modified)

## End-to-end scenario

**"Attach a PDF in chat A, jump to project B mid-upload, send from A."**

1. In chat A the user taps the paperclip and picks `report.pdf`. `useUpload.upload([asset], {kind:"draft", draftKey:"A:"})` runs the size pre-check (passes), calls `beginUpload` → a `FileRecord` (status `UPLOADING`, `clientId=temp-1`) and an `UploadTask` (`epoch=7`, progress 0) appear; `temp-1` is appended to `drafts["A:"]`. The composer chip renders instantly.
2. Bytes flow. `onProgress` → `setProgress("temp-1", 7, 0.4)`. Only that one chip's progress ring re-renders (atomic selector); the message list and text field don't.
3. The user navigates to project B. `ChatSurface` morphs; it does **not** remount. The draft lens now reads `drafts["B:proj"]` (empty) — chat A's chip vanishes from view, but `filesById["temp-1"]`, its task, and `drafts["A:"]` are all intact in the store, and the upload keeps running (the transport lives outside React).
4. The upload response arrives (still "in" project B's view, but that's irrelevant — the store is global). `reconcile([serverFile], 7)` matches `serverFile.temp_id === "temp-1"`, merges the server record (real `id`/`file_id`, status `PROCESSING`) onto the record, marks the task terminal. `drafts["A:"]` still points at `temp-1`.
5. The `UploadReconciler` poll sees `temp-1` is `PROCESSING` (and has a server id) → polls `/statuses` → `reconcile` flips it to `COMPLETED`.
6. The user returns to chat A. The lens reads `drafts["A:"]` → shows the (now `COMPLETED`) chip. Send is enabled (`hasBlockingFiles` false).
7. They send. `useChatController.submit(text, descriptors, onAccepted)` builds the optimistic message + send body **past every early-return**, then invokes `onAccepted` → the draft context's `consume("A:")`: the draft entry (text + fileIds) is dropped (the engine's file records linger harmlessly). If instead `submit` had bailed (empty text, re-entry, active run), `onAccepted` never fires and the draft — text and uploaded file — stays put. **BUG1 fixed.**

## Sequence of key operations

1. **Pick** → normalize assets (existing pickers) → `useUpload.upload(assets, target)`.
2. **Size pre-check** → `partitionBySize(assets, resolveMaxUploadMb(settings))` (finite 100 MB fallback; **BUG2**); rejections → context errors.
3. **Optimistic insert** → `beginUpload(target, records)` stamps `epoch=++counter`, adds records + tasks, links to target.
4. **Transport start** → `getUploadTransport().upload(asset, {projectId, tempId}, onProgress)`; cancel handle → `runtimeHandles`.
5. **Progress** → `setProgress(taskId, epoch, ratio)` (epoch-guarded; **BUG3**).
6. **Reconcile (one reducer)** → on response, `reconcile(user_files, epoch)` merges server record by `temp_id`, marks task terminal; rejected files → `failTask` (retryable). The upload record stays in the store; a project upload keeps its optimistic id in `projectFileIds[id]` and triggers a project-details refetch — **no invalidate + remove hand-off**. The same store is also filled by the hydrate loaders: `hydrateRecent(files)` from `/user/files/recent` and `hydrateProject(id, files)` from project-details (fetch → hydrate, never rendered).
7. **Status poll + resume** → the **single** `UploadReconciler` polls `/statuses` (3s) for **all** processing files in `filesById` (project + draft + recent), and re-polls on `AppState "active"`; both feed the same `reconcile`. Server always wins.
8. **Send** → `submit(..., onAccepted=commitDraft(draftKey))`; draft cleared only on accept.
9. **Remove / cancel** → the draft lens drops the ref (draft context `removeFile`) and calls `useUpload.remove(clientId)`, which cancels a live task + drops the engine record (no-op if there's no task).

## Key decisions & why

- **File-keyed store, not project-keyed.** The old `byProject` key made an upload "belong to" a project, so per-message attachments couldn't use it and PR 8 forked a second layer. Keying by `fileId` (as identity) with links on top is the normalized, best-practice shape for an entity shown in multiple contexts (redux normalizing-state-shape; vovk.dev). It unifies the two flows.
- **Store for the engine, context for the draft (split by who writes it).** The *engine* has detached async writers (transport callbacks, poll) + high-frequency progress → a store-outside-React with atomic selectors is the right tool (community consensus for that profile: adamhinckley zustand-vs-context). The *draft* is written only from synchronous React actions and is small → a React context fits, kept behind `useComposerDraft` so it can be promoted to a store later (its one weakness — a keystroke re-rendering the chip strip — is mitigated by `React.memo`, else the promotion) with zero component changes.
- **One store is the SSOT for every file; Query fetches-and-hydrates, never renders.** The original C was rejected fearing dual-source drift — but new backend + web research inverts that: (1) `GET /user/files/recent` returns the user's **full library**, not a time-window — no LIMIT, no time-bound WHERE, only FAILED/DELETING excluded, `ORDER BY last_accessed_at DESC` (`onyx/server/manage/users.py:1305`); "recent" is the whole pool, just sorted. (2) A project file is a **pure many-to-many association** (`Project__UserFile` join, `onyx/db/models.py:5069`) — link/unlink just add/remove a join row; the file is the SAME standalone `UserFile` by id, so project files are a **subset of the same pool** as recent. (3) `UserFileSnapshot.project_id` is hardcoded `None` (`projects/models.py:38`) — the backend itself models **file = identity, membership = association**; a normalized client cache mirrors the backend's own shape (this voids the old "speculative generality" objection). (4) Web's `ProjectsContext` is the **anti-pattern, not a model**: 5 parallel arrays of full file objects (recentFiles / allRecentFiles / allCurrentProjectFiles / currentMessageFiles / currentProjectDetails.files) hand-reconciled by a 3s poll writing into 3 of them and a 23-dep useMemo splicing link/unlink/delete — exactly the duplication the normalized store removes. (5) **Offline: no regression** — `projects` and `recent-files` are ALREADY PII-excluded from Query's MMKV persistence (`query/client.ts`), so committed files were never on disk; moving them to an in-memory store loses nothing and the future `persist` slice is identical. Drift is eliminated by the single rule "**Query never renders files**": Query stays the fetch mechanic (retry / dedup / focus-refetch / lazy `enabled`), but `onSuccess`/`select` hydrates the store and components read the store by id.
- **One reconcile reducer, server wins.** The temp→server merge, epoch guard, and rejected-file handling are written once and reused by the upload result *and* the poll — instead of Approach A's two divergent reconcile tails. Server is always the source of truth for a file's real state (React-19 optimistic-UI blueprints).
- **Progress on the task, not the record + atomic selectors.** Isolating the hot field and exposing per-file atomic selectors (never a fresh array from a selector) is the documented Zustand fix for progress re-render storms (pmndrs/zustand).
- **Epoch guard, not debounce (BUG3).** A monotonic per-run token is the only correctness fix for late/out-of-order async writes (frontendatlas js-async-race-conditions).
- **Two seams for background-readiness.** A `UploadTransport` interface + server-as-truth reconciliation mean the later background PR is a transport impl + a persist slice, not a rewrite — and orphan recovery degrades gracefully to a retry (verified: `/recent` doesn't echo `temp_id`, so auto-recovery isn't relied on).

## What existing behavior changes

- **The composer draft now persists across navigation (owner decision).** Type a message and/or attach files in chat A, jump to chat B or project C, come back — your **text and attachments are both still there**. Today the text is wiped on every conversation switch and attachments were local-state; now the whole `{ text, fileIds }` draft is keyed by conversation and restored by selection. A never-sent draft lives in memory until app restart (bounded; only non-empty drafts persist).
- **An in-flight upload now completes instead of being canceled on navigation** — it lands in your file library regardless of where you are.
- **A latent text bug is fixed too:** today `submit` clears the composer text *before* its active-run guard, so sending while a run is active loses your typed text. Now text (like attachments) clears only on an accepted send.
- **Internal-only:** a project's files and the recent/library list now render from the one `userFileStore` (id-refs resolved via `useFilesByIds`) instead of directly from TanStack Query — Query hydrates the store and is no longer rendered for files; `FileCard` reads progress via an atomic selector (no `progress` prop); `useMessageAttachments` becomes `useComposerDraft` and owns the text; `useChatController` no longer exposes `input`/`setInput`. No user-visible change from these.
