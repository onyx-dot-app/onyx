# Outlook

> The Outlook connector indexes mail as one document per thread, shared across
> the mailboxes that hold it, plus optional calendar events. Each mailbox
> decides its part of a thread from its own copy, so mailbox walks share no
> state.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE syncs document readers through the slim listing.

---

## User experience

An admin connects a Microsoft Entra app with mail access. They pick mailboxes,
Entra groups whose members' mailboxes are read, or nothing for every mailbox
the app can open. They can exclude folders by name and turn on attachments and
calendar events. A search for a mail thread returns one document for the
thread, readable by the people every message names. A recipient who deleted a
message can still read the thread. A recipient that a later reply left out
reads a copy that holds only the messages that name them.

When the app cannot open a mailbox, the run skips it. Threads that mailbox
started then belong to another mailbox, or stay as each holder's own copy.

---

## Scope

This document holds the Outlook rules: the thread key, which mailbox writes
which document, the mailbox walk, and the calendar window. Its neighbours own:
- [[microsoft-graph]]: Graph auth, national-cloud hosts and the shared sign-in
  check.
- [[connectors]]: the interfaces, prune and failure-id contracts.
- [[permission-sync]]: the EE doc sync, which reads the readers from the slim
  listing.
- [[connector-capability-checks]]: the check runner. Outlook registers named
  checks.

---

## Architecture

**Thread key.** Outlook sets a conversation index on the first message and
copies it into every reply in every mailbox. `connectors/outlook/threads.py:thread_key` takes its
22-byte root. The first message's index is the root alone
(`is_thread_root`). Copies of one message match on the Internet Message-ID.

**Who writes what.** `connectors/outlook/threads.py:plan_documents` decides, for one mailbox's
copy of a thread:
- The builder is the first message's sender when the run can open that
  mailbox, else the lowest mailbox id the first message names that the run
  can open (`designated_builder`). Every holder computes the same builder.
- The builder writes `outlook-thread:<key>` from its newest 100 messages
  (`MAX_MESSAGES_PER_CONVERSATION`). Its readers are the builder and the
  mailboxes named on every kept message, not the mailboxes that hold them.
- A mailbox the first message names but a later message leaves out gets a copy
  document, `outlook-thread:<key>:<mailbox id>`, written by the builder.
- Anything the builder cannot see is the holder's own document,
  `outlook-thread:<key>:<mailbox id>:own`.

**Listing.** Each mailbox is walked on its own, `MAILBOX_WORKERS` at a time.
Delta pages of message headers go into a `GroupedRowStore`, an anonymous SQLite
temp file per mailbox, until the mailbox is listed. The checkpoint holds
cursors only.

**Polls.** A poll lists only messages in the window. Each changed conversation
is then read whole through its outline (`_conversation_outline`) and planned by
the same function.

**Prune and permission sync.** `_slim_docs` lists each mailbox the same way and
yields the ids and readers that `plan_documents` gives. The prune diff and the
doc sync therefore see the documents that indexing built.

**Targeted re-index.** `reindex` finds the mailbox that writes each failed
document and rebuilds that mailbox's copy. Graph cannot filter on the
conversation index, so `_conversation_ids` finds a thread from the start time
in its key (`connectors/outlook/threads.py:thread_started_at`) and scans received mail from there.

---

## Contracts and traps

1. `one-planner` **Indexing and the slim listing must call the same planner.** Ids and
   readers come only from `connectors/outlook/threads.py:plan_documents`. A second rule anywhere makes prune
   delete documents that indexing wrote.
2. `builder-must-build` **The builder must be one that will build.**
   `connectors/outlook/connector.py:OutlookConnector._mailbox_available` probes a
   mailbox once per process. A permanent refusal passes it over. Any other
   error raises, because a guess hands the thread to a mailbox that never
   writes it.
3. `resume-rewalks-mailboxes` **A resumed attempt walks in-flight mailboxes again.** The listing lives in
   the temp file of the process that started it.
   `connectors/outlook/connector.py:OutlookConnector._resumable` restarts a
   mailbox that another process was listing or building.
4. `roster-fields-are-identity` **Mailboxes, groups and excluded folders are IDENTITY fields.** They decide
   each thread's builder, content and readers, so a change rebuilds every
   thread (`connectors/outlook/config.py`).
5. `calendar-rolling-window` **The calendar is a rolling window.** Prune lists events over the same
   window, so events that leave the window leave the index.
6. `event-reindex-default-calendar` **Re-index of an event reads only the default calendar.**
   `connectors/outlook/source_operations.py:OutlookSourceOperations.get_default_calendar_event` refuses other events. Occurrences, cancelled,
   private and confidential events fail, as do events while the calendar is
   off.

---

## Known issues

- **The builder's copy is the thread.** A reply the builder deleted, or filed
  in an excluded folder, is indexed nowhere. The other holders assume the
  builder writes every message that names it.
- **Excluding Sent Items drops threads the mailbox started.** The builder's
  first message sits there. Such threads leave only each holder's own
  documents of the replies.
- **A thread whose builder lost its first message is not built.** The builder
  has no root in its copy, so it writes only its own document. The other
  holders still name it as builder and keep only their own documents of the
  replies that left it out (`connectors/outlook/threads.py:plan_documents`).
- **Readers are decided over the newest 100 messages.** Messages older than
  that do not count toward a thread's readers or text.
- **Targeted re-index can miss a thread.** To find a builder,
  `_builders_held_by` reads only mail that arrived within
  `FIRST_MESSAGE_ARRIVAL_WINDOW` (7 days) of the thread start, so a first
  message kept as a draft longer is not found. Each scan stops after
  `RECEIVED_SCAN_LIMIT` messages. A rebuild reads only the walked folders
  (`_OutsideFolders`). In each case the failed document stays failed.

---

## Dependencies

- [[connectors]]: interfaces, prune and failure-id contracts.
- [[microsoft-graph]]: auth, hosts, error mapping and the sign-in check.
- [[connector-capability-checks]]: runs the Outlook named checks.

---

## Recipes

- `investigate-thread-readers` **Investigate a mail thread that is missing or has the wrong readers.** Find
  the thread key from the message's conversation index
  (`connectors/outlook/threads.py:thread_key`). Search the index for
  `outlook-thread:<key>` and its copy and own documents. Then work out the
  builder as `designated_builder` does: the first message's sender, else the
  lowest mailbox id it names that the run can open. A thread the builder cannot
  see in full leaves only own documents ([[#builder-must-build]] and the Known
  issues below). A reader missing from the thread document was left out of at
  least one kept message.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/outlook/`.
- Daily tests against a live tenant: `backend/tests/daily/connectors/outlook/`.
