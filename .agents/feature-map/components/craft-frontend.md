# Craft Frontend

> The browser side of Craft: the session store, the app-wide stream owner, turn
> settlement, the prompt queue, and the output panel with its file viewers. Its
> rules decide which of several async sources may write one session's state.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

The user chats with the agent and sees the files it writes while the turn
runs. They can type while a turn runs. The new message waits in a queue and
is sent on its own after the previous turn is saved. A queued message keeps
its attachments and its chosen model. The queue keeps working when the user
leaves Craft for another page of the app.

On reload or return, the saved transcript shows first, before the sandbox has
woken. A turn that still runs on the server comes back live. The response
stays on screen until the saved history replaces it. Stop is available for a
running turn, including one whose start request is still pending.

The user can browse the files the agent wrote, all files in the session
workspace, and the apps it built, and open any of them to preview. During a
task, new previewable files open by themselves, and one of them is shown once
per task unless the user has already chosen another file. Under each turn the
user sees which files that turn changed and which they have not opened yet. A
link to an `outputs/` file in an answer opens that file. Open files and the
message draft survive a reload in the same browser tab. Logout clears them.

The user can attach files to a draft message. Removing an attachment from the
draft does not delete the stored file, so earlier messages that used it still
work. Moving to another session or a new session clears the draft's
attachments.

When it fails:
- if the saved history cannot be read after a turn, the transcript stays and a
  retry action appears; new messages wait until it succeeds;
- if a session cannot load, a notice blocks sending until a reload works;
- if a queued message is rejected, it stays at the head of the queue for an
  explicit retry or discard;
- after a turn that failed, queued messages do not send by themselves;
- on a usage limit, the same rate-limit banner as chat appears and the queue
  stops;
- a file that cannot be previewed shows a download action.

---

## Scope

This component owns the Craft session UI: the per-session store, the app-wide
stream owner and turn attachment, settlement, the prompt queue, Stop, the
output inventory reads, the output panel and its viewers, attachment drafts,
and the per-session browser storage.

Neighbours own the rest:
- [[craft-sessions]]: turns, output cards, attachments on the server, and the
  session endpoints.
- [[craft-streaming]]: the wire format, `parsePacket`, and sub-agent routing.
- [[craft-webapp-proxy]]: the app preview and static HTML URLs.
- [[craft-external-apps]]: policy semantics, approval cards' meaning, and the
  apps pages.
- [[craft-scheduled-tasks]]: the task pages and run status.
- [[craft-admin]]: the Craft admin pages.
- [[chat-frontend]]: the rate-limit banner, drafts, and the DOCX and CSV
  helpers that Craft shares.

---

## Architecture

```
AppProvider
  CraftStreamingProvider          one useBuildStreaming for the whole app
    CraftTurnAttachment per session with a turn not owned by this tab
      and (visible on /craft, or has queued messages)
streamMessage (this tab sends)    createTurn -> streamTurnEvents
streamTurnEvents                  fetchTurnEventStream -> processSSEStream
                                  -> createStreamPacketProcessor -> store
turn_completed / no active turn   beginTurnSettlement -> reconcileCompletedTranscript
                                  -> fetchMessages + fetchActiveTurn
                                  -> refreshOutputInventory -> phase "ready"
store change                      claimQueuedMessage -> streamMessage
```

**One stream owner per app.** `web/src/providers/CraftStreamingProvider.tsx`
is mounted in `web/src/providers/AppProvider.tsx`. A tab that sends a message
owns that turn (`activeTurnLocalOwner`). For any other active turn, the
provider mounts a `CraftTurnAttachment` while the session is on screen or has
queued messages. The attachment pauses while a Stop request is pending. A
change of signed-in user reloads the page.

**Generation guards.** Each session in
`web/src/app/craft/hooks/useBuildSessionStore.ts` has an `instanceId`, a
`turnGeneration` and a `loadGeneration`. Every async write first checks that
these still match the values it started with. A stale stream, history read or
inventory read then drops its result instead of overwriting a newer turn.
`streamMessage` bumps `turnGeneration`. `loadSession` bumps `loadGeneration`.

**Settlement.** `turnSettlement` has the phases `reconciling`, `failed` and
`ready`. It starts on a terminal packet (normally `turn_completed`) or when the
attach finds that the turn is not active. `reconcileCompletedTranscript` needs
a terminal outcome: the `turn_completed` packet, or `fetchKnownTurn` when the
packet was missed. It then reads messages, checks for a successor turn
(another tab), reads history again if one started during the read, starts an
inventory read, and replaces the live stream items with saved history. A
scheduled run settles on its saved run status instead.

**The queue.** `enqueueMessage` adds to `queuedMessages`. The dispatcher in
`web/src/app/craft/hooks/useBuildStreaming.ts` subscribes to the store and
calls `claimQueuedMessage`, which marks the head `starting` inside one store
update. The claim succeeds only when the session is `active`, has no active
turn and no error, and its settlement is `ready` for the current generation.

**Output inventory.** `refreshOutputInventory` reads
`GET /build/sessions/{id}/outputs`, a flat list of paths, sizes and revisions.
Reads for one session run one after another, and a change of runtime aborts
them. A complete response replaces the known files. A partial response merges
and keeps files it did not scan. During a turn, completed shell and edit tool
calls schedule a read through a short coalescing queue. Settlement does the
final read. Only a non-silent read after a complete baseline can open tabs,
and `automaticallySelectOutput` selects at most once per task
(`outputSelectionLocked`).

**Output cards and viewers.** Turn cards come from the server
(`web/src/lib/build/hooks.ts:useOutputCards`), not from the live inventory. The
open panel marks the active file's card as viewed.
`web/src/lib/build/hooks.ts:useFilePreview` keeps one payload per viewer,
keyed by path, inventory revision and an explicit reload counter.
`web/src/app/craft/components/OutputPanel.tsx` keeps a few recent file viewers
mounted but hidden and `inert`, so switching tabs does not fetch them again.

---

## Contracts and traps

1. `confirmed-completion-releases-queue` **Only confirmed completion releases
   the queue.** `claimQueuedMessage` in
   `web/src/app/craft/hooks/useBuildSessionStore.ts` requires `turnSettlement.phase ===
   "ready"` for the current generation. A connection loss, a mounted
   component, a status change or an approval pause must not grant it. A failed
   or skipped scheduled run reloads history but never releases the queue.
2. `atomic-queue-claim` **The claim is atomic.** It happens inside one `set`
   call, so repeated store events or two mounted hooks cannot send one prompt
   twice. Do not read the queue head and send it outside the claim.
3. `queued-request-id-stable` **A queued prompt keeps one request id across
   retries.** `streamMessage`
   (`web/src/app/craft/hooks/useBuildStreaming.ts:useBuildStreaming`) sends `queue:{instanceId}:{messageId}` as
   `client_request_id`, and the server returns the same turn for a repeat
   ([[craft-sessions#client-request-id-idempotent]]). Discarding a failed head
   first reconciles (`removeQueuedMessage`), because a lost response can hide
   an accepted turn.
4. `generation-check-after-await` **Check the generation after every await.** A
   new async path that writes to a session must compare `instanceId` and
   `turnGeneration` (or `loadGeneration` for loads) after each await. Without
   it, an old turn's result can replace a successor's transcript or select tabs
   for it.
5. `history-after-terminal-outcome` **History replaces the live transcript
   only after a terminal outcome.** Do not start settlement on a clean stream
   close. The attach loop reconnects while the backend turn is active.
6. `stop-owns-interrupt-only` **Stop owns only the interrupt request.**
   `requestStop` deduplicates by `instanceId` and generation in the
   module-level map
   `web/src/app/craft/hooks/useBuildStreaming.ts:stopRequests`. The stream owner, not Stop, handles
   completion. A Stop before the server accepts the turn keeps
   `wasInterrupted`, and `streamMessage` sends the interrupt once it has a
   `turn_id`.
7. `passive-reads-never-select` **Silent inventory reads never open or select
   tabs.** Focus reads, background refreshes and a manual refresh with no
   running turn call `refreshOutputInventory` with `silent`. A read from an
   older turn may update file metadata but must not select for the successor.
8. `session-storage-prefix` **Per-session Craft browser state lives in
   `sessionStorage` under keys that start with `onyx:craft:`.** Logout
   (`web/src/lib/users/svc.ts:logout`) removes every `sessionStorage` key with
   that prefix or with `onyx:draft:craft:`. A new key with another prefix, or
   in `localStorage`, survives logout and can leak between accounts on a
   shared browser. Per-user preferences that must survive logout, such as
   `web/src/app/craft/utils/llmPreferences.ts`, use `localStorage` with the
   user id in the key. Browser snapshots are display hints only; live responses
   always replace them.
9. `output-links-untrusted` **Output links in answers are untrusted.**
   `web/src/app/craft/utils/pathSanitizer.ts:parseOutputLink` accepts only
   `outputs/` paths and rejects hidden segments, encoded separators, control
   characters, queries and fragments. The message supplies the session id, so
   a link cannot open another session's file.
10. `attachment-draft-scope` **Attachment drafts are scoped to one session
    visit.** `web/src/app/craft/contexts/UploadFilesContext.tsx` binds the
    draft to an attachment scope. An upload that completes after the scope
    changed must not add files to the new draft. `removeFile` and `clearFiles`
    change only the draft, never the stored files. The server enforces the
    quota ([[craft-sessions#attachment-quota-row-lock]]).
11. `preview-error-split` **A file preview error is not always transient.**
    `web/src/lib/build/hooks.ts:useFilePreview` discards content on auth and not-found errors and keeps it
    on other failures. Keep that split when you add a viewer.
12. `model-only-after-pick` **A send carries a model only after an explicit
    picker change.** `web/src/app/craft/components/ChatPanel.tsx:ChatPanelContent` sends
    `modelOverride ?? modelBySession[id]`, and `modelBySession` holds only
    choices the user made. The server rewrites the session's saved model
    whenever a send names one ([[craft-sessions]]). A client that always sends
    the picker's shown value replaces the saved model with a default. A queued
    message keeps the choice made when it was queued.
13. `pre-provisioned-session-shared` **The pre-provisioned session is shared
    between tabs.** `ensurePreProvisionedSession` creates or reuses the user's
    one empty session, and `consumePreProvisionedSession` claims it on the
    first send. On the welcome page,
    `web/src/app/craft/hooks/usePreProvisionPolling.ts` asks the server every
    few seconds whether the session is still empty. When another tab has
    claimed it, the hook resets the state and provisions again. A failed check
    does not provision again, so a network error cannot replace a good session
    ([[craft-sessions#empty-session-shared]]).

---

## Decisions

- **The queue lives in the browser.** The server allows one turn per session
  and rejects a second one. Holding later prompts in the browser keeps the
  server simple. The cost is the first known issue below.
- **Settlement reads saved history instead of trusting the live stream.** The
  stream has no replay ([[craft-streaming#no-replay-buffer]]), so a tab that
  reconnected mid-turn may have missed events. Saved history is complete.

---

## Known issues

- **Unsent queued messages are lost on reload or tab close.** They exist
  only in the store.
- **An expired turn record needs a page reload.** If the server forgot a
  turn before settlement read it, the session stays in recovery until the
  page reloads. Saved history stays.
- **The store handles a run status that the backend never sets.**
  The store and the task pages treat `AWAITING_APPROVAL` as in
  flight, but no backend code writes it ([[craft-scheduled-tasks]]).

---

## Dependencies

- [[craft-sessions]]: every endpoint the store calls, `client_request_id`
  idempotency, the pre-provisioned session, and output cards.
- [[craft-streaming]]: the SSE format, `turn_completed`, `parsePacket`, and
  `classifySubagentEvent`.
- [[craft-webapp-proxy]]: Browser tab URLs and static HTML capabilities.
- [[rate-and-usage-limits]]: the 429 that stops the queue.
- [[chat-frontend]]: the rate-limit banner, `useDraft`, and the DOCX and CSV
  helpers in `web/src/lib/`.

---

## Recipes

- `new-viewer` **A new viewer.** Copy `PdfPreview` in
  `web/src/app/craft/components/output-panel/` and its test. List the viewers
  with `ls web/src/app/craft/components/output-panel/`. Render it from
  `FilePreviewContent` and load bytes through `useFilePreview` with the
  inventory revision, so reloads and hidden tabs behave like the others. Keep
  the error split ([[#preview-error-split]]).
- `new-session-state` **A new piece of per-session state.** Copy `outputSelectionLocked` in
  `BuildSessionData`. List the fields with
  `git grep -n 'interface BuildSessionData' -A110 web/src/app/craft/hooks/useBuildSessionStore.ts`.
  If an async path writes it, guard the write
  ([[#generation-check-after-await]]). If it must survive reload, store it
  under an `onyx:craft:` key in `sessionStorage`
  ([[#session-storage-prefix]]); copy
  `web/src/app/craft/services/outputPanelPreferences.ts`.
- `reproduce-queue-bug` **Reproduce a queue or settlement bug.** Open two tabs on one session. Queue
  two messages during a turn in one tab and reload the other. Each message must
  run once, in order. The store tests in `web/src/app/craft/hooks/` build
  these states without a browser; copy a settlement test there.

---

## Verification

- Store, streaming and queue: the tests in `web/src/app/craft/hooks/` and
  `web/src/providers/`.
- Viewers and services: the tests next to each file in
  `web/src/app/craft/components/` and `web/src/app/craft/services/`.
- By hand: stop a turn whose start is still pending, and confirm that the turn
  ends as stopped.
