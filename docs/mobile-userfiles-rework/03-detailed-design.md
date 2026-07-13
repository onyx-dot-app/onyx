> Status: active · Task: mobile-userfiles-rework

# Mobile file-upload module restructure — Detailed Design

## Scope note — a store (engine) + a context (draft), separated by concern

State splits into **two mechanisms by concern (SoC)**:

- **`userFileStore`** (zustand store) — the file/upload **engine** and the **single source of truth (SSOT) for EVERY file record**: uploads, draft attachments, project files, AND recent/library files all live in one id-keyed `filesById`. It owns file identity + upload tasks (progress/epoch/status) + the reconcile reducer + per-target upload errors + committed membership (`projectFileIds`) + the recent list (`recentIds`). Written from async, out-of-React work (transport callbacks, poll, reconciler, fetch-hydrate) at high frequency → a store, with atomic selectors, is the right tool.
- **`ComposerDraftContext`** (React context) — the composer **draft**: `Record<draftKey, { text, fileIds }>`. Written **only from synchronous React user actions** (type / pick / remove / send); the async/high-frequency file work lives in the store. That makes context a principled fit here, not a compromise. **The store-vs-context split for the draft is UNCHANGED by the SSOT pivot** — the draft still holds only `{text, fileIds}` id-refs that resolve against the store.

**Query is a fetch-and-hydrate LOADER, never rendered for files.** TanStack Query keeps its fetch mechanics (retry / dedup / focus-refetch / lazy `enabled`), but its results **hydrate the store on success** (`hydrateProject` / `hydrateRecent`) and are **never rendered** for file lists. Projects, drafts, and the recent picker hold only **id-references** that resolve against `filesById` via `useFilesByIds`. One source, several loaders → the dual-source drift that sank the original normalized approach is eliminated by the rule **"Query never renders files"** (project-details' non-file fields like name/personas may still render from Query).

This also persists the **whole composer draft per conversation** across navigation, not just attachments. Today the message text is a single `input` `useState` in `useChatController` (`hooks/useChatController.ts:168`), wiped on conversation change by `ChatSurface` (`:87-89`) **and** cleared inside `submit` at `:217` — which runs *before* the active-run early-return at `:223`, so the typed text is lost on a bailed send exactly like the attachments (a second face of BUG1). Now `text` and `fileIds` live together in the draft context keyed by `draftKey`; navigation restores both (the provider is mounted above the morphing `ChatSurface`, so it never remounts), and both clear only on an accepted send.

**Why context for the draft, store for the engine (owner decision):** the engine needs selector granularity (progress ticks), out-of-React writers, and future persist/background — all store strengths. The draft needs none of those: it's small, synchronous, React-written UI state. **The draft is hidden behind the `useComposerDraft(draftKey)` hook** — components never call `useContext` directly — so if the context's coarse re-render ever bites (a keystroke re-rendering the chip strip; see notes), it is first mitigated with `React.memo` on the chips, and if still needed, **promoted to a store as a contained change to the hook + provider only (zero component edits).** The seam is deliberate.

## State design (the stores are the "schema" here)

Database design: **N/A — no DB or backend change.** The client-side analog is the two store shapes; every field is justified below. All state is a plain JSON-serializable `Record` (never a `Map`) — immutably spread-cheap, atomically selectable by key, `persist`-ready for the future background PR. Cancel handles (non-serializable) live in a module-level side table outside state.

### Store 1 — `state/userFileStore.ts` (the engine + SSOT; rewrite of `uploadStore.ts`)

Owns file identity + upload lifecycle **and is the SSOT for every file record** (upload / draft / project / recent). Knows targets only as opaque tags; never touches composer text. It never imports Query, but Query's loaders write into it via `hydrateProject`/`hydrateRecent`.

#### `filesById: Record<string, FileRecord>` — the identity registry (SSOT)

**Holds EVERY file record** — uploads, draft attachments, project files, and recent/library files — in one id-keyed map. Every surface renders by resolving ids against this map; nothing renders files from Query. This mirrors the backend's own shape (file = identity, membership = association).

| Field (on `FileRecord`) | Type | Why it exists |
|---|---|---|
| `clientId` | `string` (key) | Stable identity for the record's whole life. For an upload it is the temp id; it **never moves** when the server swaps in the real id (only `file.id`/`file.file_id` fill in). For a registered recent file it is the server id. Keying by this lets one file be referenced from multiple contexts without duplication. |
| `file` | `ProjectFile` | The UI-facing record (`chat/contracts/projects.ts`). Optimistic until reconcile, then server-authoritative. Same shape every consumer (`FileCard`, `fileDescriptors.ts`, `MessageRow`) already renders. |
| `source` | `"upload" \| "recent"` | Distinguishes an in-flight upload (has a task) from a registered already-server file (no task). Drives whether a task/poll applies. |

#### `tasksById: Record<string, UploadTask>` — first-class uploads

| Field (on `UploadTask`) | Type | Why it exists |
|---|---|---|
| `taskId` | `string` (key) | `=== clientId` of the record it drives (one task per upload). Separate map so progress churn never spreads a `filesById` record. |
| `clientId` | `string` | Back-reference to the record it reconciles into. |
| `fileKey` | `string` | `buildFileKey(asset)` = `${size}|${name[:50]}` — matches the server's echoed `temp_id_map` key. |
| `target` | `UploadTarget` | `{kind:"draft",draftKey}` or `{kind:"project",projectId}` — **the one deliberate seam.** Lets the project lens select its in-flight uploads and lets `beginUpload` route the optimistic id to `projectFileIds` for a project target. The engine treats it as an opaque tag — it does not read draft text or Query. |
| `epoch` | `number` | Monotonic run token stamped at `beginUpload`. Every store write for this task carries the epoch it captured; applied only if `tasksById[taskId]?.epoch === epoch`. Late writes from a superseded run self-invalidate. BUG3 fix + concurrency invariant. |
| `status` | `"uploading" \| "succeeded" \| "failed" \| "canceled"` | Task lifecycle (distinct from the file's server status). |
| `progress` | `number` (0..1) | The hot field. Read only by the owning card via an atomic selector. |
| `error` | `string \| null` | Per-file upload error; rendered on the card and **dies with the task** — no floating banner to go stale (the BUG3 ghost). |

#### `errorsByTarget` + counter

| Field | Type | Why it exists |
|---|---|---|
| `errorsByTarget` | `Record<string, string[]>` | Context-level (size-precheck / picker) errors, keyed by `targetKey` (`"draft:"+key` / `"project:"+id`). They are products of an *upload attempt*, so they belong to the engine, not the draft. Cleared on the next pick. |
| `epochCounter` | `number` | Monotonic source for `epoch`; `++` on every `beginUpload`. |

#### `projectFileIds` + `recentIds` — membership/list id-refs (hydrated from loaders)

| Field | Type | Why it exists |
|---|---|---|
| `projectFileIds` | `Record<number, string[]>` | A project's **committed membership** as an ordered list of `clientId`s, hydrated from project-details (`hydrateProject`). A project file is a pure many-to-many association (`Project__UserFile` join) — the same standalone `UserFile` by id — so the project holds only id-refs into `filesById`, never copies. Optimistic uploads append here; link/unlink mutate it optimistically and a refetch re-hydrates. |
| `recentIds` | `string[]` | The **recent/library list** as an ordered list of `clientId`s, hydrated from `/user/files/recent` (`hydrateRecent`). `/recent` returns the user's FULL library (no LIMIT, no time-bound WHERE; excludes only FAILED/DELETING; `ORDER BY last_accessed_at DESC`) — "recent" = the whole file pool, just sorted. The picker renders by resolving these ids against `filesById`. |

```ts
const runtimeHandles = new Map<string, { cancel: () => void }>(); // module-level; NOT store state
```

### Draft — `components/chat/ComposerDraftProvider.tsx` (React context; new)

Pure per-conversation UI state, written only from synchronous React actions. References files by `clientId`; never copies file data. The provider holds one map keyed by conversation and is mounted **above `ChatSurface`** (in `app/(app)/_layout.tsx`) so it survives the surface's morph. Follows the app's one existing context precedent (`components/sidebar/SidebarProvider.tsx`).

| Field | Type | Why it exists |
|---|---|---|
| `drafts` | `Record<string, DraftState>` | `draftKey → { text, fileIds }`. `DraftState = { text: string; fileIds: string[] }`. `draftKey = \`${sessionId ?? "new"}:${projectId ?? ""}\``. `text` is the composer message; `fileIds` is the **durable** attachment list (survives upload completion + recent-attach, unlike the engine's transient tasks). A `draftKey` change just reads a different entry — conversations are isolated by construction, no reset effect. |

`fileIds` is durable here because a draft attachment persists after its upload finishes and for recent-attached files that never had a task. This is the **draft's own** membership list — distinct from a project's `projectFileIds` (server-authoritative committed membership, hydrated from project-details), because the draft's list is client-owned UI state with no server association behind it.

**Re-render note (the context tradeoff):** the provider `value` is one object, so any draft change re-renders every consumer of the context — a keystroke (which changes `text`) also re-renders the chip strip (which only reads `fileIds`), because context has no per-field selectors. At 1–3 chips this is negligible; the mitigation if it ever matters is `React.memo` on the chip strip with a stable `fileIds` prop (unchanged across keystrokes), and the escape hatch is promoting the draft to a store (contained to this provider + the `useComposerDraft` hook — see scope note).

### `UploadTarget`
```ts
export type UploadTarget =
  | { kind: "draft"; draftKey: string }
  | { kind: "project"; projectId: number };
export const targetKey = (t: UploadTarget) =>
  t.kind === "draft" ? `draft:${t.draftKey}` : `project:${t.projectId}`;
```

## Class / interface design

### `userFileStore` actions
```ts
interface UserFileActions {
  beginUpload(target: UploadTarget, records: FileRecord[]): number;  // stamps epoch, adds records+tasks(tagged target); returns run epoch
  setProgress(taskId: string, epoch: number, progress: number): void;   // epoch-guarded
  failTask(taskId: string, epoch: number, message: string): void;       // epoch-guarded; file.status → FAILED (retryable)
  reconcile(serverFiles: ProjectFile[], epoch?: number): void;          // ONE reducer; match by temp_id else id; server wins; marks task terminal. Now also applied by the unified poll across surfaces (project + draft + recent).
  hydrateProject(projectId: number, files: ProjectFile[]): void;        // upsert server records into filesById (NO task) + set projectFileIds[projectId]
  hydrateRecent(files: ProjectFile[]): void;                            // upsert server records into filesById (NO task) + set recentIds
  registerExisting(file: ProjectFile): string;                          // recent file → FileRecord (source "recent", no task); returns clientId (= server id)
  removeFile(clientId: string): void;                                   // cancels a live task via runtimeHandles, drops the record
  setTargetErrors(target: UploadTarget, errors: string[]): void;
  clearTargetErrors(target: UploadTarget): void;
}
```
No `consumeDraft`, no `projectLinks`, no `handoff` in the store — those are composer/project concerns handled in the hooks (below). `hydrateProject`/`hydrateRecent` upsert records **without** creating tasks (these are already-server files) and set the membership/recent id-lists; they are the write-side of Query's fetch-and-hydrate loaders. `reconcile` is UNCHANGED (match by temp_id else id, server wins) and is now the single reconcile path for every surface via the unified poll.

### `userFileStore` selectors (atomic)
```ts
const EMPTY_IDS: readonly string[] = Object.freeze([]);
export const useUploadProgress = (taskId: string) =>
  useUserFileStore((s) => s.tasksById[taskId]?.progress ?? 0);              // hot path — one card per tick
export const useFilesByIds = (ids: readonly string[]) =>
  useUserFileStore(useShallow((s) => ids.map((id) => s.filesById[id]?.file).filter(Boolean)));
export const useTargetUploadIds = (target: UploadTarget | null) =>          // in-flight ids for a target (project optimistic list)
  useUserFileStore(useShallow((s) => target == null ? EMPTY_IDS
    : Object.values(s.tasksById).filter((t) => sameTarget(t.target, target)).map((t) => t.clientId)));
export const useTargetErrors = (target: UploadTarget) =>
  useUserFileStore((s) => s.errorsByTarget[targetKey(target)] ?? EMPTY_ERRORS);
export const useProjectFileIds = (projectId: number | null) =>              // committed membership id-list (resolve via useFilesByIds)
  useUserFileStore((s) => projectId == null ? EMPTY_IDS : s.projectFileIds[projectId] ?? EMPTY_IDS);
export const useRecentFileIds = () =>                                        // recent/library id-list (resolve via useFilesByIds)
  useUserFileStore((s) => s.recentIds);
```
`setProgress` spreads the task not the record → `useFilesByIds` stable across ticks. `subscribeWithSelector` enabled for a future imperative progress bar. **Never** select `state.filesById`/`state.tasksById` wholesale for a list.

### `ComposerDraftContext` — value shape (React context)
```ts
interface ComposerDraftValue {
  drafts: Record<string, DraftState>;   // read draft = drafts[key]
  setText(draftKey: string, text: string): void;
  addFiles(draftKey: string, ids: string[]): void;
  removeFile(draftKey: string, id: string): void;
  consume(draftKey: string): void;              // accepted composer send: drop the whole entry (text + fileIds)
  consumeAttachments(draftKey: string): void;   // accepted starter send: drop fileIds, KEEP text (matches today)
}
```
Backed by a `useReducer`/`useState` inside `ComposerDraftProvider`. Actions are stable (`useCallback`); `value` is `useMemo`'d. **Consumers never call `useContext(ComposerDraftContext)` directly** — only `useComposerDraft(draftKey)` does, so the storage mechanism (context now, store later if promoted) is an implementation detail behind that one hook.

### Transport seam: `api/files/transport.ts` (new) — unchanged from prior design
```ts
export interface UploadHandle { result: Promise<CategorizedFiles>; cancel: () => void; }
export interface UploadTransport {
  kind: "foreground" | "background";
  upload(asset: NormalizedAsset, opts: { projectId: number | null; tempId: string },
         onProgress: (ratio: number) => void): UploadHandle;
}
let active: UploadTransport = foregroundTransport;
export const getUploadTransport = () => active;
export const configureUploadTransport = (t: UploadTransport) => { active = t; };
```
`foregroundTransport` wraps the `createUploadTask`-migrated uploader; the background impl injects later via `configureUploadTransport`.

### Hooks
```ts
// CORE — hooks/useUpload.ts (new). Orchestrates userFileStore + transport. The only place upload logic lives.
export function useUpload(): {
  upload: (assets: NormalizedAsset[], target: UploadTarget) => string[];  // size-check → beginUpload → transport → reconcile/fail; returns clientIds
  registerExisting: (file: ProjectFile) => string;                         // recent → record; returns clientId
  remove: (clientId: string) => void;                                      // cancel + drop
};
```
For a **project** target, `useUpload` does **not** hand off to Query and does **not** `removeFile` — the upload STAYS in the store. The optimistic `clientId` is appended to `projectFileIds[projectId]` at `beginUpload`; after `reconcile`, the hook refetches project-details, which re-hydrates membership via `hydrateProject` (server-authoritative). The *store* never imports Query — the hook triggers the refetch.

```ts
// LENS A — hooks/useComposerDraft.ts (rename/rewrite of useMessageAttachments.ts).
// The SOLE consumer of ComposerDraftContext; composes it with the userFileStore.
export function useComposerDraft(draftKey: string): {
  text: string; setText: (t: string) => void;               // ComposerDraftContext
  files: ProjectFile[]; errors: string[]; descriptors: FileDescriptor[]; hasBlockingFiles: boolean;
  addDocuments: () => Promise<void>; addImages: () => Promise<void>;
  addRecent: (file: ProjectFile) => void; removeFile: (id: string) => void;
  dismissErrors: () => void;
  consume: () => void;             // draft context consume(draftKey)
  consumeAttachments: () => void;  // draft context consumeAttachments(draftKey)
};
```
`const ctx = useContext(ComposerDraftContext)`; `text = ctx.drafts[draftKey]?.text ?? ""`; `files = useFilesByIds(ctx.drafts[draftKey]?.fileIds ?? EMPTY_IDS)`. `addDocuments/addImages` → `const ids = useUpload.upload(assets, {kind:"draft",draftKey}); ctx.addFiles(draftKey, ids)`. `addRecent(file)` → `const id = useUpload.registerExisting(file); ctx.addFiles(draftKey,[id])`. `removeFile(id)` → `ctx.removeFile(draftKey,id); useUpload.remove(id)` (remove no-ops if no task). `errors = useTargetErrors({kind:"draft",draftKey})`.

```ts
// LENS B — hooks/useProjectFiles.ts (rewrite). Project file PANEL. Reads committed membership from the STORE, never Query.
// `committedFiles` (project-details fetch result) is now a HYDRATION INPUT (→ hydrateProject), not the rendered list.
export function useProjectFiles(projectId: number | null, committedFiles: ProjectFile[] | null | undefined): {
  files: ProjectFile[]; errors: string[]; isBusy: boolean;
  addDocuments: () => Promise<void>; addImages: () => Promise<void>;
  linkRecent: (fileId: string) => Promise<void>; removeFile: (fileId: string) => Promise<void>;
  dismissErrors: () => void;
};
```
On `committedFiles` change (the project-details fetch result), the hook calls `hydrateProject(projectId, committedFiles)` — that is its fetch-and-hydrate step. It then renders from the store: `committed = useFilesByIds(useProjectFileIds(projectId))`; `optimistic = useFilesByIds(useTargetUploadIds({kind:"project",projectId}))`; `files = [...optimistic, ...committed]` (dedup by id). The committed list is read **from the store** — never rendered from Query. Uploads via `useUpload.upload(assets, {kind:"project",projectId})`. `linkRecent`/`removeFile` stay server-backed (`linkFileToProject`/`unlinkFileFromProject`) but now update `projectFileIds` **optimistically** then refetch project-details to re-hydrate. **No per-surface poll** — the single `UploadReconciler` covers project files.

`useRecentFiles` (the recent picker's loader) fetches `/user/files/recent` and calls `hydrateRecent`; the picker reads `recentIds` from the store (via `useRecentFileIds` + `useFilesByIds`) and never renders from Query; no per-surface poll.

### `useChatController` change (BUG1, both faces)
```ts
export interface ChatController {         // input/setInput REMOVED — composer text now lives in ComposerDraftContext
  messages; chatState; stop; isHydrating;
  submit: (text: string, files?: FileDescriptor[], onAccepted?: () => void) => void;
}
```
`submit` drops the `input` fallback and the `setInput("")` at `:217`; calls `onAccepted?.()` once, synchronously, after the active-run guard and before `createChatSession` (guaranteed-committed → fixes BUG1; before any `await` → still snappy).

## New files

| File | Responsibility |
|---|---|
| `mobile/src/state/userFileStore.ts` (+ test) | (rewrite of `uploadStore.ts`) file engine + SSOT: `filesById` (every file record) / `tasksById`(target-tagged) / `errorsByTarget` / `projectFileIds` / `recentIds` / `epoch` + actions (incl. `hydrateProject`/`hydrateRecent`) + atomic selectors + `runtimeHandles`. |
| `mobile/src/components/chat/ComposerDraftProvider.tsx` (+ test) | (new) React context: `Record<draftKey,{text,fileIds}>` via reducer + `setText`/`addFiles`/`removeFile`/`consume`/`consumeAttachments`; mounted above `ChatSurface`. |
| `mobile/src/api/files/transport.ts` | `UploadTransport` + `foregroundTransport` (createUploadTask) + configure/get. |
| `mobile/src/hooks/useUpload.ts` (+ test) | Core engine hook: size pre-check, upload orchestration, registerExisting, remove/cancel; project upload appends to `projectFileIds` + refetches project-details (no Query hand-off). |
| `mobile/src/hooks/useComposerDraft.ts` (+ test) | (rename of `useMessageAttachments.ts`) sole `ComposerDraftContext` consumer; composes it with `userFileStore`: text + attachment refs. |
| `mobile/src/hooks/useRecentFiles.ts` (+ test) | Fetch-and-hydrate loader: fetches `/user/files/recent` and calls `hydrateRecent`; the picker reads `recentIds` from the store, never Query. |
| `mobile/src/components/chat/UploadReconciler.tsx` (+ test) | Null component: **the SINGLE poller** — 3s `/statuses` poll over all `isServerProcessingStatus` files in `filesById` (project + draft + recent) + `AppState "active"` re-poll → `userFileStore.reconcile`. |
| `mobile/src/components/ui/BearerImage.tsx` (+ test) | Shared authed-image primitive. |

## File structure (tree)
```
mobile/src/
├── state/
│   ├── userFileStore.ts               (rewrite of uploadStore.ts — file engine + SSOT: filesById/projectFileIds/recentIds + hydrate actions)
│   └── __tests__/userFileStore.test.ts (rewrite)
├── api/files/
│   ├── transport.ts                   (new: UploadTransport seam)
│   ├── upload.ts                      (modified: createUploadTask cancelable uploader)
│   └── files.ts                      (unchanged)
├── hooks/
│   ├── useUpload.ts                   (new: core engine; project upload → projectFileIds + refetch, no hand-off)
│   ├── useComposerDraft.ts            (rename of useMessageAttachments.ts; sole draft-context consumer + userFileStore)
│   ├── useProjectFiles.ts             (rewrite: reads projectFileIds from store + prepends in-flight tasks; no Query-rendered list, no per-surface poll)
│   ├── useRecentFiles.ts              (loader: fetch /recent → hydrateRecent; picker reads recentIds from store)
│   └── useChatController.ts           (modified: drop input/setInput; submit(text, files?, onAccepted?))
├── components/
│   ├── chat/
│   │   ├── ComposerDraftProvider.tsx  (new: React context {text,fileIds} by draftKey + reducer)
│   │   ├── ChatSurface.tsx            (modified: composer text from draft; drop setInput effect; consume-on-accept)
│   │   ├── UploadReconciler.tsx       (new)
│   │   ├── FileCard.tsx               (modified: useUploadProgress + task error; drop progress prop)
│   │   ├── InputBar.tsx               (modified: text from draft; drop progressById; React.memo chip strip)
│   │   ├── ProjectContextPanel.tsx    (modified: drop progressById prop pass)
│   │   └── AttachmentImage.tsx        (modified: → BearerImage wrapper)
│   ├── avatars/AgentImage.tsx         (modified: → BearerImage wrapper)
│   └── ui/BearerImage.tsx             (new)
├── lib/files.ts                       (modified: DEFAULT_MAX_UPLOAD_MB + resolveMaxUploadMb)
└── app/(app)/_layout.tsx             (modified: mount <ComposerDraftProvider> + <UploadReconciler/>)
```

## What each file will contain

- **`state/userFileStore.ts`** — the `create()` engine store + `UserFileActions`. `reconcile` builds `byTemp`/`byId` maps, resolves each record by temp_id (fresh) else id (poll), guards epoch when provided, `record.file = {...record.file, ...serverFile}`, marks the task terminal on a non-`UPLOADING` status. `removeFile` cancels via `runtimeHandles`, deletes task+handle+record. Exports atomic selectors + `sameTarget`/`targetKey` helpers + `EMPTY_IDS`.
- **`components/chat/ComposerDraftProvider.tsx`** — a React context provider over a `useReducer` holding `Record<draftKey,{text,fileIds}>`; `setText` upserts `drafts[key].text` (keeping the `fileIds` array reference stable across keystrokes); `addFiles`/`removeFile` mutate `fileIds`; `consume` deletes the entry; `consumeAttachments` clears `fileIds` only. Actions `useCallback`-stable, `value` `useMemo`'d; exposes `ComposerDraftContext`.
- **`hooks/useUpload.ts`** — `upload(assets, target)`: `partitionBySize(assets, resolveMaxUploadMb(settings))` → `setTargetErrors` → build optimistic records → `const epoch = beginUpload(target, records)` (for a project target, `beginUpload` appends the optimistic `clientId`s to `projectFileIds[projectId]`) → per file `getUploadTransport().upload(...)` (progress → `setProgress(tempId, epoch, r)`; handle → `runtimeHandles`) → `await result` → `reconcile(user_files, epoch)` + rejected → `failTask`; **project post-step:** refetch project-details (re-hydrates membership via `hydrateProject`) — NO `invalidateQueries`, NO `removeFile`; the upload stays in the store. Returns the optimistic `clientId[]`.
- **`hooks/useComposerDraft.ts`** — the sole `ComposerDraftContext` consumer; composes it (text + `fileIds`) with `userFileStore` (files via `useFilesByIds`) + `useUpload` (upload/register/remove) + `useTargetErrors`. Derives `descriptors`/`hasBlockingFiles`. This hook is the seam: swapping the draft's storage (context → store) later touches only this file + the provider.
- **`hooks/useProjectFiles.ts`** — `committed = useFilesByIds(useProjectFileIds(id))` (read from the store, hydrated from project-details) with `optimistic = useFilesByIds(useTargetUploadIds({project:id}))` prepended; uploads via `useUpload`; link/unlink update `projectFileIds` optimistically then refetch project-details to re-hydrate. NO Query-rendered committed list; NO per-surface poll (the single `UploadReconciler` covers it).
- **`hooks/useRecentFiles.ts`** — fetches `/user/files/recent` (Query owns the fetch mechanics) and on success calls `hydrateRecent(files)`; the picker reads `recentIds` via `useRecentFileIds` + `useFilesByIds`, never rendering from Query; no per-surface poll.
- **`components/chat/UploadReconciler.tsx`** — the SINGLE poller: 3s interval polling `getUserFileStatuses` for **every** `isServerProcessingStatus` file in `filesById` (project + draft + recent) → `userFileStore.reconcile`; `AppState "active"` re-poll (guarded/debounced); dropped-response orphan stays a retryable `failed` task.
- **`components/chat/ChatSurface.tsx`** — `const draft = useComposerDraft(draftKey)`; `<InputBar value={draft.text} onChangeText={draft.setText} .../>`; delete the `setInput("")` effect; `sendWithAttachments(message?)`: `submit((message ?? draft.text).trim(), draft.descriptors, message == null ? draft.consume : draft.consumeAttachments)`.
- **`lib/files.ts`** — `DEFAULT_MAX_UPLOAD_MB = 100` + `resolveMaxUploadMb`; `partitionBySize` uses it.
- **`components/ui/BearerImage.tsx`** — `useAuthToken()` → memoized `{ uri, headers }`, `cachePolicy="none"`, neutral placeholder, `radius`. `AttachmentImage`/`AgentImage` → wrappers.
- **`hooks/useChatController.ts`** — drop `input`/`setInput`; `submit(text, files?, onAccepted?)`; `onAccepted` at the committed point.

## Integration points

- **`userFileStore` ↔ `ComposerDraftContext`** — coordinated only in `useComposerDraft` via synchronous writes (attach = upload→ctx.addFiles; remove = ctx.removeFile→useUpload.remove). No cross-mechanism async, no refcount; unreferenced file records linger in-memory (bounded, wiped on restart/logout-purge). The `ComposerDraftProvider` must be mounted **above `ChatSurface`** (in `app/(app)/_layout.tsx`) so the draft survives the surface morph.
- **TanStack Query `userProject` / `userRecentFiles`** — demoted to **fetch-and-hydrate LOADERS** (never rendered for files): they keep fetch mechanics (retry / dedup / focus-refetch / lazy `enabled`) but on success the hooks call `hydrateProject` / `hydrateRecent` to write records + id-lists into the store; components render files only from the store. Project-details' non-file fields (name/personas) may still render from Query. No project hand-off, no per-surface poll patching Query.
- **`useChatController`** — loses `input`/`setInput`; `submit(text, onAccepted)`. Only caller is `ChatSurface`. Still dual-writes `file_descriptors`.
- **`useWorkspaceSettings`** — the single `user_file_max_upload_size_mb` read moves into `useUpload`.
- **Pickers/uploader/poller** (`api/files/*`) — reused; `upload.ts` gains the `createUploadTask` path behind the transport.
- **`InputBar`/`FileCard`/`ProjectContextPanel`/`MessageRow`** — unchanged lens shapes; `InputBar` text from the draft; `progressById` prop removed.
- **`app/(app)/_layout.tsx`** — mount `<UploadReconciler/>`.
- **Logout/account-switch purge** (`sessionManager.purgeCache`) — both new stores must clear on identity change (they hold PII-adjacent references); wire the reset alongside the existing Query purge.

## Important notes before implementation

- **SoC boundary is the point:** `userFileStore` must never import the draft context or Query, and must not read draft text. `ComposerDraftContext` holds only ids + text. **Components must consume the draft only through `useComposerDraft`, never `useContext(ComposerDraftContext)` directly** — that hook is the seam that makes a later context→store promotion a contained change (hook + provider only). Enforce in review.
- **Draft = context is a deliberate, revisitable choice:** the draft is small, synchronous, React-written UI state, so context fits. Its one weakness — a keystroke re-rendering the chip strip (context has no per-field selectors) — is negligible at 1–3 chips, mitigated first by `React.memo` on the chip strip (stable `fileIds` prop), and only promoted to a store if that proves insufficient.
- **Coordination is synchronous, not async** — attach/remove/consume are plain synchronous writes in the hook; no drift window, no refcount GC. Do not add one.
- **The `target` tag is the only engine↔context seam** — keep it an opaque tag; do not let the store branch on draft vs project beyond selecting in-flight uploads and routing the optimistic id to `projectFileIds`.
- **Verified backend facts:** upload echoes `temp_id` (`models.py:36`) → reconcile reliable. `/recent` does not (`users.py:1266`) → dropped-response orphans are retryable failed tasks. `/statuses` keyed by `file.id`. Unset max-upload resolves to 100 MB → `DEFAULT_MAX_UPLOAD_MB=100`.
- **`onAccepted` timing** — after the active-run guard, before the `createChatSession` await (committed-but-snappy).
- **Text-input caveat (IME/cursor):** the composer `TextInput` is controlled by the draft context's `text`; React state is synchronous + untransformed so standard controlled behavior holds; fallback is a local mirror synced to the context.
- **`reconcile` atomic in one `set`**; a project upload stays in the store — the optimistic id is appended to `projectFileIds` and a project-details refetch re-hydrates membership (dedup by id in the lens avoids double-count). No `invalidateQueries` + `removeFile` hand-off.
- **`createUploadTask` migration** changes the response/error surface — re-validate `api/files/upload.ts` guards.
- **`cachePolicy="none"` stays** in `BearerImage` (non-auth-keyed URL leak risk). **AppState re-poll guarded/debounced.** **In-memory this rework:** the store is JSON-shaped for the future background `persist`; the draft context is in-memory (persisting it for draft-survives-app-kill is one reason a later store promotion may make sense).
- **Send-gating divergences retained** (owner-chosen): FAILED blocks send; Enter = newline.
- **Retention (SSOT cost):** the store now holds the session's **whole library** (bounded by library size, in-memory, wiped on restart). Membership stays server-authoritative via `hydrateProject`/`hydrateRecent` + optimistic add/remove + refetch. **Dangling refs are safe** — `useFilesByIds` filters missing ids, so a DELETING-skew id or a not-yet-hydrated ref simply doesn't render. Optional LRU eviction can come later.
- **Offline — NO regression:** `projects` and `recent-files` are ALREADY PII-excluded from Query's MMKV persistence (`query/client.ts`), so committed files were never on disk. Moving them to an in-memory store loses nothing, and the future `persist` slice is identical.
- **Why the SSOT reversal is correct (backend + web evidence):**
  1. `GET /user/files/recent` returns the user's **FULL library** — no LIMIT, no time-bound WHERE; excludes only FAILED/DELETING; `ORDER BY last_accessed_at DESC` (`onyx/server/manage/users.py:1305`). "Recent" = the whole pool, just sorted.
  2. A project file is a **pure many-to-many association** (`Project__UserFile` join, `onyx/db/models.py:5069`); link/unlink add/remove a join row; a project file is the SAME standalone `UserFile` by id — a subset of the same pool as recent.
  3. `UserFileSnapshot.project_id` is hardcoded `None` (`projects/models.py:38`) — the backend models file = identity, membership = association; a normalized client cache mirrors that shape (voids the old "speculative generality" objection).
  4. Web `ProjectsContext` is the **anti-pattern**: 5 parallel arrays of full file objects (recentFiles / allRecentFiles / allCurrentProjectFiles / currentMessageFiles / currentProjectDetails.files) hand-reconciled (a 3s poll writes 3 of them; a 23-dep useMemo splices link/unlink/delete). The normalized store replaces exactly that duplication.
  5. Offline re-check confirms no regression (see above) — committed files were never persisted.
- **Tests:** `userFileStore` (reconcile temp→server + server-wins, epoch no-op, failTask retryable, removeFile cancels, target selectors; `hydrateProject`/`hydrateRecent` upsert-without-task + set `projectFileIds`/`recentIds`; `useProjectFileIds`/`useRecentFileIds` selectors); `ComposerDraftProvider` (text/fileIds isolation by key, consume vs consumeAttachments, setText keeps fileIds ref stable); `useUpload` (size fallback = BUG2, transport, project appends to `projectFileIds` + refetch — no hand-off); `useComposerDraft` (context+store compose, persist-across-key, BUG1 survives bailed submit); `useProjectFiles` (reads `projectFileIds` from store + prepends in-flight tasks, no Query-rendered list); recent picker reads `recentIds` from store; `useChatController` (submit text + onAccepted); `UploadReconciler` (single poller over all processing files); `BearerImage`. Gate: `bun run typecheck && bun run lint && bunx jest`. Native rebuild remains an owner HARD GATE.

## As-built refinements (post-implementation adversarial review)

Three correctness fixes surfaced by an adversarial review of the C implementation, all test-locked:

- **`reset()` on `userFileStore`, wired into `sessionManager.purgeCache`.** The store now holds committed file records, so it must clear on identity change alongside the Query purge — otherwise account A's recent/project files (and the global `recentIds`) briefly render for account B. `reset()` also cancels + clears in-flight upload handles.
- **`clearCommittedTasks` in `hydrateProject`.** A project upload's task stays `succeeded` after reconcile; once the file is committed (in `projectFileIds`), the succeeded task is cleared so it can't resurrect the file as a phantom "optimistic" card after a later unlink. **Scoped to the hydrating project target** so a recent-picker refetch can't clear a project-owned task mid-upload. (`hydrateRecent` clears nothing — only `useProjectFiles` renders from tasks.)
- **`useComposerDraft.removeFile` de-references, doesn't hard-delete.** It calls `upload.remove` (hard-delete of the shared `filesById` record) **only for an in-flight upload owned by this draft** (`tasksById[id]?.status === "uploading"`); a recent-attached or already-committed shared record is only dropped from the draft's `fileIds`, never deleted — so it survives on the recent picker / other drafts / project panels.
- **Known negligible:** a transient double-render if an independent project-details refetch hydrates a just-uploaded file in the sub-millisecond window before that upload's own `reconcile` echoes its `temp_id`; self-heals the instant `reconcile` lands.

## Upload errors surface as toasts (web parity)

Follow-up (owner-requested): upload errors now show as **toasts**, not the inline box — matching web, whose `ProjectsContext` uses `toast.warning`/`toast.error` for exactly these. New `hooks/useToast.ts` (a module-level `useSyncExternalStore` store ported from `web/src/hooks/useToast.ts`) + `components/ui/ToastHost.tsx` (native Portal stack, mounted once at root in `app/_layout.tsx`). `useUpload` emits `toast.warning` for size rejections and `toast.error` for upload/picker failures; `useProjectFiles` link/unlink errors → `toast.error`. This **retires the whole `errorsByTarget` plumbing** — `errorsByTarget`/`runEpochByTarget`/`setTargetErrors`/`clearTargetErrors`/`useTargetErrors`/`isRunCurrent` and the `errors`/`dismissErrors` lens outputs are gone (the per-*task* `epoch` guard for progress/reconcile is untouched). `purgeCache` also calls `toast.clearAll()` on identity change. BUG3's stale-banner class is now structurally impossible: there is no persistent per-conversation error state, only ephemeral toasts.

## Selector surface trimmed

The store exports only the **shared/hot** selectors — `useFilesByIds` (3 consumers) and `useUploadProgress` (hot per-tick). The four single-consumer selectors listed earlier (`useTargetUploadIds`, `useProjectFileIds`, `useRecentFileIds`, `useTargetHasActiveUpload`) were **inlined into their one lens** (`useProjectFiles` / `useRecentFiles`) as plain `useUserFileStore((s) => …)` calls — keeping the store/lens boundary clean (store = state + shared reads; lens = its own surface-specific derivation).

## Final model — store owns file DATA, surfaces own membership (owner-driven)

The store no longer stores membership id-lists. `projectFileIds` / `recentIds` are **gone**; the store is a pure file-data cache:

- **`filesById`** (data, keyed by stable `clientId`) + **`serverIdToClientId`** (an *identity index* — resolves a server-id reference to the live record, even for a just-uploaded file still keyed by its temp id) + the upload lifecycle (`tasksById`, `progressById`, `epochCounter`). Nothing else.
- `hydrateProject` / `hydrateRecent` merged into one **`upsert(files, clearTasksForTarget?)`** — upserts records + maintains the index, and (with a target) clears that target's succeeded tasks for the upserted files. Resolution order everywhere: **index → scan fallback (`findClientIdByServerId`) → new** (the scan keeps it correct if the index ever misses; `registerExisting` uses the same resolution so it references, never duplicates).
- **`useFreshFiles(files)`** resolves a list of server files to their live store records, falling back to the given object until the store is seeded — this is what keeps a committed file's status live.
- **`useProjectFiles` / `useRecentFiles`** hold their own id-list (from the Query prop), seed the store via `upsert`, and render via `useFreshFiles`. **`useComposerDraft` is unchanged** (resolves its draft clientIds via `useFilesByIds`).
- **Known low-severity transient:** during the narrow window where an external project-details refetch lands *after* the server links an upload but *before* the upload POST response reconciles, a file can render twice (temp-keyed optimistic + server-keyed committed) — self-heals within ~one round-trip when `reconcile` matches the echoed `temp_id`. Inherent to dedup-by-`file.id`; the backend doesn't carry `temp_id` in project-details to bridge it earlier.

## Recent-files sheet shows in-flight uploads (web parity)

`useRecentFiles` prepends in-flight uploads (all `tasksById` clientIds → records) to the fetched `/recent` list, deduped by `file.id` — mirroring web's optimistic `allRecentFiles`. `FilePickerSheet` renders a spinner (via the `leading` slot) for `UPLOADING`/`PROCESSING`/`INDEXING` rows with an "Uploading…/Indexing…" hint, and **disables the tap while `UPLOADING`** (no server id yet → not linkable; web keeps it tappable, mobile is stricter). The consumers' existing `linkableRecent` filter removes files already attached to the current surface, so a surface's own in-flight upload doesn't appear in its own picker.
