# Context Assembly

> The content the LLM actually sees: the system prompt, the custom agent prompt,
> project and user files, the trailing reminder, and the token budget and
> truncation rules that decide what survives a long conversation. Core-chat-loop
> owns the machinery that runs a turn; this component owns what gets fed into it.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE, with query-expansion and search-flow prompt variants in EE
**Owns:**
`backend/onyx/chat/prompt_utils.py`, `prompt_formatting.py`,
`backend/onyx/llm/token_budget.py`, `backend/onyx/agents/compaction.py`,
`backend/onyx/chat/COMPRESSION.md`, `incognito.py`, `incognito_context.py`,
`backend/onyx/prompts/`, `backend/ee/onyx/prompts/`

**Read first:** `backend/onyx/chat/README.md`. Its "Reasons / Experiments" section
is the rationale behind the ordering and the reminder placement in this document.
The functions that assemble the final message list
(`prepare_prompt`, `_create_context_files_message`, `_create_file_tool_metadata_message`,
`build_chat_reminder`) live in `backend/onyx/chat/prompt_utils.py`, which
this component owns. This document describes what those functions build and
why; [[core-chat-loop]] describes when the shared runtime calls them.

---

## 1. What the user experiences

Almost none of this is visible directly, which is what makes it dangerous to
change. The user notices its failures as unrelated-looking bugs:

- The assistant forgets a file the user uploaded ten messages ago, even though
  the user never removed it from the conversation.
- A custom agent's instructions get followed for a few turns, then quietly stop
  mattering as the chat grows.
- Project files that the user is actively working from get dropped, or worse,
  never get dropped, and crowd out the actual question.
- Citations point at the wrong document, or the model narrates its citation
  numbers instead of using them cleanly ("I'll cite document 5 here").
- In a long conversation, the assistant seems to "lose the thread": it repeats
  a question it already answered, or forgets a decision from earlier without
  any error appearing.
- A weak model starts producing garbled tool calls or ignoring the system
  prompt entirely, only when a custom agent is attached.

None of these produce a stack trace. They show up as "the AI got worse" reports
days after a prompt-ordering change, which is why this component carries the
project's highest review bar for tone-deaf edits (see §9).

---

## 2. Surfaces

This component has no HTTP endpoints of its own. It is consumed entirely from
inside [[core-chat-loop]]'s `backend/onyx/chat/agent.py:ChatAgent` and
`prepare_chat_turn` (`backend/onyx/chat/prepare.py`). Two endpoints expose
its token math to the frontend:

| Method | Path | Notes |
|---|---|---|
| GET | `/chat/max-selected-document-tokens` | Upper bound for document selection in the UI. |
| GET | `/chat/available-context-tokens/{id}` | Remaining budget for a session, for the file-upload UI. |

### Environment configuration

| Variable | File | Effect |
|---|---|---|
| `GEN_AI_INPUT_TOKEN_SAFETY_MARGIN` | `configs/model_configs.py` | Fraction held back from the model input ceiling; also reserves space when estimating output allowance. |
| `GEN_AI_NUM_RESERVED_OUTPUT_TOKENS` | `configs/model_configs.py` | Minimum useful output allowance for `TokenBudget.output_allowance`; a smaller calculated allowance returns `None`. |
| `DISABLE_VECTOR_DB` | referenced in `files.py:extract_context_files` | Changes whether oversized files fall back to search or to `FileReaderTool` metadata. |

The SDK uses constants in `agents/compaction.py`: a 0.85 trigger ratio, a 0.2 recent-context ratio,
and a summary output cap of 2,048 tokens. `COMPRESSION_TRIGGER_RATIO` remains declared in chat configuration,
but has no callers and does not control SDK compaction.

No admin-configured setting overrides prompt text directly; the base system
prompt is DB-backed (see §4.1) and editable per deployment.

---

## 3. Data model

This component reads persona and project rows but does not own them
([[agents-personas]], [[projects]] do). What matters here:

- `Persona.system_prompt`, `Persona.task_prompt`, `Persona.replace_base_system_prompt`,
  `Persona.datetime_aware`: drive §4.1 and §4.2.
- `Project.instructions`: the fallback source for the custom agent prompt when
  the default persona is used inside a project
  (`prepare.py:get_custom_agent_prompt`).
- `Memory` rows, surfaced through `db/memory.py:get_memories` into a
  `UserMemoryContext`, feed the per-user "User Information" message that follows
  the system prompt (`prompt_utils.py:build_user_information_prompt`).
- `ChatMessage.last_summarized_message_id` and a summary `ChatMessage` row
  (`parent_message_id` pointing at the response where compaction occurred) persist
  summary text and its last covered SDK message ID. See `COMPRESSION.md` and §4.9.
- `UserFile.token_count`: computed at upload time with the LLM tokenizer (or a
  default fallback tokenizer when the model's is unknown), used by
  `extract_context_files` to decide whether a file fits.

No new tables belong to this component. A schema change here should be treated
as a signal to reconsider the design (see root `CLAUDE.md` on avoiding
migrations).

---

## 4. How it works

### 4.0 The assembled context, annotated

Per step, `backend/onyx/chat/prompt_utils.py:prepare_prompt` produces this order:

```
[system]                     -- base prompt and tool guidance, or persona replacement
[user information]           -- per-user SYSTEM message, when using the base prompt
[history before last user]   -- retained history and any compaction summary
[custom agent prompt]        -- USER message (§4.2)
[context / project files]    -- document JSON (§4.3-4.4)
[last user message]          -- current question, with its attachments
[tool calls and responses]   -- output from this turn's steps (§4.7)
[file metadata notices]      -- oversized or omitted files and available retrieval tools
[reminder]                   -- optional USER message wrapped in <system-reminder>
[image-limit notice]         -- optional final reminder if formatting removed images
```

The SDK rebuilds this list for each model call and after compaction. Prompt assembly
borrows history without modifying its messages or nested payloads. It creates replacement
message containers and metadata for prompt changes. Formatting returns detached model
messages, including native image parts. Selected lazy file descriptors are copied before
loading; their synchronized content cache remains shared.

### 4.1 System prompt

`prompt_utils.py:build_system_prompt` assembles the base prompt in this order:

1. The base prompt text, with `{{CURRENT_DATETIME}}`, `{{CITATION_GUIDANCE}}`,
   and `{{REMINDER_TAG_DESCRIPTION}}` placeholders resolved
   (`prompts/prompt_utils.py:apply_prompt_placeholders`). The base prompt itself
   comes from `prompt_utils.py:get_default_base_system_prompt`, which reads the
   default persona's `system_prompt` from the DB, falling back to
   `prompts/chat_prompts.py:DEFAULT_SYSTEM_PROMPT`.
2. The org-wide part of "User Information"
   (`prompt_utils.py:_build_shared_user_information_section`): a framing
   paragraph announcing the per-user message, then the Team/company context
   (`prompts/prompt_utils.py:get_company_context`). The per-user part — Basic
   Information, Organization Profile, Language, User Preferences, Memories
   (`_build_user_specific_section`) — is **not** in the system message:
   `build_chat_prompt` emits it via `build_user_information_prompt` as a second
   `SystemMessage`, placed immediately after the shared system prompt by `prepare_prompt`.
   Keeping names, emails and memories out of the
   system message makes it identical for every user with the same base
   prompt, tool guidance (e.g. `enable_memory_tool` toggles the memory
   section) and resolved date, so the head cache breakpoint
   (`llm/prompt_cache`) is shared across those users instead of per user.
   `include_user_info=True` (token estimation, tests) inlines the per-user part
   into the returned string instead.
3. Citation guidance when requested by the caller. Normal chat keeps dynamic
   citation guidance in the trailing reminder (§4.5); token estimation requests
   all guidance to reserve a worst-case allowance.
4. Per-tool guidance sections, each gated on the turn's configured tools
   list (not the tools exposed in this cycle): search, internal-search, web-search, open-URL, Python, image
   generation, memory (`prompts/tool_prompts.py`). `include_all_guidance=True`
   forces every section on; `calculate_reserved_tokens` uses this to size a
   worst-case prompt up front (§4.8).

If `persona.replace_base_system_prompt` is set, none of this runs. The
persona's own `system_prompt`, run through `prompt_utils.py:process_prompt_template`,
becomes the system message (`backend/onyx/chat/prompt_utils.py:build_chat_prompt`).
Project instructions remain a separate custom context message (§4.2).

If the default base prompt is an empty string and no replacement is set, the
custom agent prompt (if any) is promoted to `MessageType.SYSTEM` instead of
`USER`, and stops moving (`backend/onyx/chat/prompt_utils.py:build_chat_prompt`).

### 4.2 Custom agent prompt

Resolved once per turn by `prepare.py:get_custom_agent_prompt(persona, chat_session)`,
during `prepare.py:prepare_chat_turn`, before workers start. The agent uses
captured instructions without reading the database mid-turn. Project and custom-agent instructions
are combined; agent instructions take precedence on conflicts. A default agent
uses project instructions alone. When `replace_base_system_prompt` is set, the
agent instructions form the system message and project instructions remain a
separate context message.

Project files and custom-agent files are combined and deduplicated before
context budgeting. Prompt loading, file-reading tools, and overflow retrieval
must retain both sources. See [[projects]] §4.4-4.5.

Unless it has been promoted into the system message (§4.1),
`prompt_utils.py:build_chat_prompt` builds the custom prompt as a `UserMessage`.
`prompt_utils.py:prepare_prompt` inserts it
directly above the last user message, ahead of the project/context files. It
therefore "moves": on turn *N+1* it sits above the turn *N+1* user message, not
where it appeared in turn *N*'s history.

### 4.3 Files: user uploads vs. project files

The two kinds take different load paths, and the product intent differs. The
code preserves it. Project files (and persona-attached files) load through
`files.py:extract_context_files`. User uploads do not. Attached files
become history messages in `chat_utils.py:convert_chat_history`, one message per
text file, tagged with `file_id`.

`db/user_file.py:prepare_chat_file_inputs` reads attachment token counts and processing
status in one batch on the caller thread before `chat/files.py:load_chat_files` starts content workers. Workers receive
scalar values, so they cannot share the caller's database session. Plaintext
loading stays parallel, with at most 16 workers; raw bytes stay lazy. While a
file is processing or indexing, inline extraction does not replace the worker's
canonical plaintext.

- **User-uploaded files** (attached to a single message) are a "point in time"
  inclusion. They stay where they were uploaded in the message history and, as
  the conversation grows past them, they drift toward the truncation boundary
  like any other old message and can eventually be dropped (with a forgotten-files
  notice, §4.6). This is an accepted tradeoff, not a bug: constantly dragging
  every uploaded file forward would crowd out the actual conversation.
- **Project files** move forward with the conversation every cycle, the same
  way the custom agent prompt does, and `chat/README.md` states that they must
  not be dropped by history truncation. Project files that fit are injected.
  Oversized sets are routed to search or file metadata by
  `files.py:extract_context_files`. They are assumed to be central to
  what the user is doing, not a needle-in-a-haystack fact to search for.

At upload, every file is token-counted with the target LLM's tokenizer where
known, falling back to a default tokenizer otherwise. Images get an assumed
token count rather than a real one. `extract_context_files` handles only
the project and persona files. It compares the aggregate token count of
context-eligible files (it skips metadata-only types) against
`(llm_max_context_window - reserved_token_count) * 0.6` (the 60% ceiling exists
because the tokenizer is approximate and to avoid starving history on every
project-heavy turn). Below that ceiling, text files load as full text
(`_create_context_files_message`, §4.4), and images load as image files.
Metadata-only types never load as text. They produce `FileToolMetadata`
entries instead. At or above it, they fall back to
`use_as_search_filter` (vectorized, RAG-retrievable through the search tool) or,
when the vector DB is disabled, to lightweight `FileToolMetadata` entries that
name whichever retrieval tool this cycle actually offers
(`backend/onyx/chat/prompt_utils.py:_create_file_tool_metadata_message`).

Project files are additionally vectorized into the search index when the vector DB is enabled
(`chat/README.md`, "Projects"), independent of whether they fit in context, so
a model with a smaller window can RAG over the project instead of losing it.

### 4.4 Document JSON shape

`backend/onyx/chat/prompt_utils.py:_create_context_files_message` renders in-context files as:

```
Here are some documents provided for context, they may not all be relevant:
{
  "documents": [
    {"document": 1, "title": "Hello", "contents": "Foo"},
    {"document": 2, "title": "World", "contents": "Bar"}
  ]
}
```

The `document` key holds a single integer, deliberately, so the model can cite
it as a bare number without inventing an ID format or narrating it in its
reasoning (`chat/README.md`, "Reasons / Experiments": the key is named
`document`, not `citation_id`, specifically to avoid the model writing things
like "I should reference citation_id: 5"). Title (and, for search-tool
documents, metadata) precede the long `contents` field, because the model
attends better to fields placed early relative to a long trailing block even
though it technically has global access to the whole message.

Context-file document numbers come from the same source mapping used by citation rendering.
Existing file IDs retain their numbers; new files cannot reuse historical source numbers.

Search-tool documents follow the same `document`-keyed shape in a `ToolResultMessage`.
Each tool result can contain multiple documents. Project/context files are injected
as a `UserMessage` containing one document list.

### 4.5 Reminder

`backend/onyx/chat/prompt_utils.py:build_chat_reminder` picks the trailing reminder each cycle, in
priority order: an image-generation reminder if this cycle just ran image gen,
an open-URL nudge if a web search just ran, the open-URL tool is actually
available this cycle, and this is not the last cycle, otherwise `prompt_utils.py:build_reminder_message`, which
merges:

- The user-configured persona task prompt (`persona.task_prompt`), if any.
- `prompts/chat_prompts.py:LAST_CYCLE_CITATION_REMINDER`, appended only on the
  final cycle (`out_of_cycles`).
- `prompts/chat_prompts.py:REQUIRE_CITATION_GUIDANCE` (unless the task prompt
  already carries it), `ANSWER_COVERAGE_GUIDANCE`, and
  `ANSWER_COMPLETENESS_REMINDER`, appended whenever a search-like tool has run
  this turn (`should_cite_documents or always_cite_documents`) and kept on every
  subsequent cycle until the turn ends, not just the cycle the search ran in.
- `prompts/chat_prompts.py:FILE_REMINDER`, appended when the Python tool
  generated a file this turn.

When nonempty, the reminder is a `UserMessage` with `PromptMetadata.is_reminder=True`.
`prepare_prompt` appends it last. `prepare_model_messages` wraps its text in
`<system-reminder>` tags. Image-limit formatting can append a second reminder
that identifies omitted images. Both are request-only content, not recorded conversation history.

### 4.6 Truncation and the forgotten-files notice

The SDK fits the complete assembled request before each model call (§4.9).
It first tries a summary. If required, it removes older user turns at boundaries
that keep tool calls and results together. It rebuilds the prompt for each candidate.
The current question and required instructions must fit; otherwise execution fails
with `ContextLimitError` instead of sending an oversized request.

`prepare_prompt` compares retained file IDs with `all_injected_file_metadata`.
Missing files produce a notice after conversation history and before the reminder.
The notice names available retrieval tools; it does not promise access without them.
This notice participates in the same complete-request budget check.

`messages_for_model` filters unfinished tool calls and unmatched results for replay.
The recorded partial output remains intact for storage and inspection.

### 4.7 Tool calls in history

Within one turn, the SDK retains `ToolResultMessage` content for later steps.
Chat prompt assembly deduplicates repeated search passages without changing stored results.

On a later turn, `chat_utils.py:capture_chat_history` marks ordinary saved tool
results with `PromptMetadata.omit_tool_result_content`. `prepare_prompt` replaces
only their model-facing content with `TOOL_CALL_RESPONSE_CROSS_MESSAGE`.
Stored evidence remains available for citations and display. Image-generation results
are the exception: saved file IDs and revised prompts remain visible to the model.

Tool call *arguments* stay in history. For the internal search tool, they are
the original arguments the LLM supplied. Query expansion (EE:
`backend/ee/onyx/prompts/query_expansion.py`) changes only what the tool runs.
It does not rewrite the saved arguments.

### 4.8 Token budget

`agents/compaction.py:context_budget` applies `GEN_AI_INPUT_TOKEN_SAFETY_MARGIN`
to the configured model input limit. This ceiling controls input fitting.
`llm/token_budget.py:resolve_token_budget` separately estimates the output allowance
from catalog context/output limits. When that allowance is available, the runtime
caps `max_tokens`; otherwise it keeps the request's existing output setting.

Before any of this runs, `prompt_utils.py:calculate_reserved_tokens` is called
once per turn (`prepare.py:prepare_chat_turn`) to reserve space for the
system prompt (worst case, via `include_all_guidance=True`) plus the custom
agent prompt plus attached-file tokens, computed against the
placeholder-substituted final text so a long directory-profile value cannot
invalidate the reservation after the fact. This reservation must happen before
`extract_context_files` decides whether project files fit (§4.3): reversing
that order would let files claim space the prompt still needs.

See [[file-store-and-user-files]] §4.4 for metadata capture and content-loading
session boundaries.

The SDK counts the assembled request, including tool definitions, before each
model call. It reuses that count for the output allowance. Each run caches token
counts by exact text, so unchanged content avoids repeated tokenization. Changed
prompts, tool definitions, and results get new counts. After counting a request,
the cache retains only text used by that request. It clears during execution cleanup.

Provider-specific counters from `get_llm_token_counter` also cache counts locally,
with a 1,024-entry limit. These counters support prompt preparation across the
feature agents. Neither cache shares conversation content across tenants. SDK
context fitting retains its own counting rules; it does not use the display and
tracing estimates attached to prepared messages.

### 4.9 Compression

Each agent fits its context before a model call in `agents/runtime.py:_compact_context`.
This includes child agents and each model in a comparison turn.

1. Apply any retained checkpoint to the source history, then assemble and count the full request.
2. Above 85% of the model's safety-adjusted input ceiling, call `agents/compaction.py:compact_history`.
   It keeps a recent suffix within a target of 20% of that ceiling and summarizes the older prefix.
   Summary calls fold in the previous summary and use bounded batches and a time budget.
3. Choose a stable message ID as the inclusive cutoff. Tool-call groups stay together.
   Request-only additional context cannot be the cutoff because it disappears on the next turn.
4. Reassemble and count the request with the summary. If proactive summarization fails while
   the original request still fits, continue with that request and log the failure.
   Otherwise try oldest-first truncation. If required input still cannot fit, raise `ContextLimitError`.

Uploaded attachment text is replaced with file names and IDs in summary input.
Assistant text and tool results still contribute findings. Project/persona files are
injected during prompt assembly rather than included in the summary source.
Attachment loading currently happens before the checkpoint removes covered history;
the summary policy does not skip that loading work.

For content-retaining sessions, `db/chat_response.py` saves a changed, nonempty summary
with the response: `message_type=SUMMARY`, `parent_message_id=response.id`, and
`last_summarized_message_id=checkpoint.covered_through_message_id`.
An unchanged summary creates no new row. Emergency truncation has an empty summary
in run state and creates no empty SUMMARY row.

On the next turn, `db/chat.py:find_summary_for_branch` selects a summary attached to
the nearest ancestor in the chosen branch. The runtime locates its cutoff in restored
messages. An absent cutoff or a cutoff splitting a tool-call group is logged and ignored.
Content changes do not invalidate the cutoff through a hash check.

Comparison models share project-file selection sized for the smallest selected input window.
Each model then fits and compacts its own assembled request using its own input limit.
See `backend/onyx/chat/COMPRESSION.md` for persistence and attachment contracts.

### 4.10 Incognito

`incognito.py:current_turn_persists_content` reads the pinned
`IncognitoRecordMode` for the session from a contextvar
(`shared_configs.contextvars.get_current_incognito_record_mode`), never the live
admin setting, so a mid-session setting change cannot alter an in-flight
session's contract. Only `FULL_HISTORY` writes assembled content into
`chat_message` rows; `USAGE_ONLY` writes content-free rows
(`incognito.py:content_free_file_descriptors`) and instead carries the live
conversation in an out-of-Postgres store for the session's lifetime
(`incognito_context.py:load_incognito_context`,
`incognito_context.py:save_incognito_response`).

`incognito_context.py` stores canonical root messages and child response records in one JSON envelope.
Root messages decode once, including prompt metadata. Their serializer retains search and research citation sources, but omits other tool details and attachment bytes.
The envelope has a sliding one-hour TTL, a one-megabyte limit, and at most 200 root messages.
It evicts older child records before older root messages. An oversized new response leaves stored state unchanged.
The `incognito_ctx:v2` namespace starts fresh temporary sessions after deployment. Old content expires through its existing TTL.
The obsolete tenant-scoped `incognito_ctx:pending_teardowns` set contains only session IDs and has no TTL.
Deployment cleanup can delete that obsolete metadata key after old writers drain; no content migration or old-format reader is needed.

The store uses `CacheBackend`, but remains available only with Redis.
Postgres cache must not receive USAGE_ONLY content. The internal cache accessor enforces this boundary.
`_locked_incognito_state` supplies one tenant/session lock for saves and teardown.
A single cache write replaces root and child state together. Version checks reject stale history replacements.
Response saves retry transformations against fresh state and reject conflicting replay of the same response.

Teardown sets a separate tombstone before waiting for cleanup. Reads and writes check that marker.
Reads check after decoding the envelope. Locked writes check before loading and before storing the updated state.
Its TTL covers the history and stream-buffer lifetimes. Cleanup removes the envelope under the session lock.
`CacheBackend.delete_prefix` removes every buffered stream for that session, including chunks without metadata.
It matches literal prefixes within one tenant. Redis and Postgres implement the same operation.
The operation does not stop concurrent writers; stream writers still check session teardown and clean up on completion.

A cache set tracks pending cleanup IDs, registered before teardown fences the session.
Retry work reads at most 100 members without scanning unrelated cache keys.
A busy session queues the existing cleanup task after 60 seconds; periodic cleanup also retries it.
IDs remain until history and buffered output are removed, even if task publication fails.
Set insertion is atomic and requires no application-level index lock.
Session liveness checks batch key existence without loading conversation content.

Lock acquisition waits at most five seconds per attempt; the lease lasts 60 seconds.
Ownership checks and bounded retries follow the existing lock policy. They do not make lease expiry and writes atomic.
Retry callbacks must not perform external writes. Errors and logs omit temporary conversation content.

### Worked examples (from `chat/README.md`)

Custom agent, no files. `CA` moves to sit above each new user message.
These examples omit persona task reminders and use `R` for a tool-related reminder:

```
Turn 1: S, U1, TC, TR, A1, CA, U2, A2
Turn 2 (tool call happens): S, U1, TC, TR, A1, U2, A2, CA, U3, TC, TR, R, A3
```

Project plus one uploaded file. The uploaded file (`F`) stays fixed in place
above the message it was attached to; the project (`P`) and the custom agent
prompt (`CA`) both move forward, agent before project:

```
Turn 1: S, CA, P, F, U1, A1
Turn 2: S, F, U1, A1, CA, P, U2, A2
```

Reminders within one turn move to the end of whatever the history looks like
at that moment, every cycle:

```
Cycle 1: S, U1, TC, TR, R
Cycle 2 (another tool call): S, U1, TC, TR, TC, TR, R, A1
```

---

## 5. Contracts and invariants

1. **Reminders follow conversation history and file notices.** Prompt formatting
   may append an image-limit reminder after the chat reminder. These reminders
   must remain outside the stable, cacheable history prefix.
2. **The custom agent prompt is a `UserMessage`, not part of the
   system prompt, unless it has replaced the system prompt outright.** It moves
   every step to sit before context files and the last user message. If
   `persona.replace_base_system_prompt` is set, the agent instructions become
   the system message. Project instructions remain a separate moving message.
3. **Selected project text is reinjected after history compaction.** Uploaded
   text can leave the retained history. Native images still follow provider image limits.
4. **User-uploaded files do not move.** They stay attached to the point in the
   history where they were uploaded and drift toward truncation like any other
   old message; this is intentional, not a bug to fix.
5. **Truncation is oldest-first and must emit a forgotten-files notice for a
   dropped file whenever file metadata is available.**
   `prepare_prompt` derives missing files from the retained history and names only
   retrieval tools available in that step.
6. **Reserved tokens (`calculate_reserved_tokens`) must be computed before the
   rest of the budget is spent**, specifically before `extract_context_files`
   decides whether project files fit. Reversing this order lets a large
   project starve the prompt.
7. **The document JSON shape, especially the bare-integer `document` key and
   its ordering ahead of `contents`, is load-bearing for citation reliability.**
   This is not cosmetic; changing the key name or field order is a citation
   regression, not a refactor.
8. **Incognito must not persist assembled content when the pinned mode is
   `USAGE_ONLY`.** Any new field added to the assembled context (a new section,
   a new file type) needs an explicit incognito decision, not a default
   assumption that it is safe to store.
9. **The system prompt and custom agent prompt are rebuilt every cycle, not
   once per turn.** Step preparation rebuilds dynamic reminders and citation
   guidance. Base tool guidance uses the configured tool set; file notices use
   the tools available in that step.

---

## 6. Relationships

**Depends on**
- [[agents-personas]]: persona fields (`system_prompt`, `task_prompt`,
  `replace_base_system_prompt`, `datetime_aware`, `user_files`) drive nearly
  every branch in §4.1-4.3.
- [[projects]]: `Project.instructions` and project files are a source of both
  the custom agent prompt and the project-files section.
- [[file-store-and-user-files]]: upload-time tokenization and file loading
  (`chat/files.py:load_chat_files`) and project-file extraction.
- [[chat-preferences]]: user memories, preferences, and language settings
  feeding `build_user_information_prompt`.
- [[tools-framework]]: configured tools determine system-prompt guidance.
  Tools offered in the current step determine file-notice retrieval instructions.
- [[llm-providers]]: `llm.config.max_input_tokens` and tokenizer resolution
  drive the entire token budget.

**Depended on by**
- [[core-chat-loop]]: chat preparation captures instructions and files; `ChatAgent`
  builds each step's prompt through the shared SDK. Research and coding agents also
  use the SDK context-fitting stage.
- [[citations]]: the citation processor consumes the document JSON and
  citation mapping this component builds.
- [[streaming-protocol]]: none directly, but a malformed assembled message can
  surface as a malformed packet.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| edits prompt text (base system prompt, tool guidance, reminders) | Run an eval, not just a unit test (§8). Re-read `chat/README.md`'s "Reasons / Experiments" before moving any sentence between sections. |
| reorders the assembled context | [[core-chat-loop]]'s §4.4 restates this ordering; both docs must change together. Re-verify the worked examples in §4 above still hold. |
| adds a new context element (a new file type, a new injected section) | Decide its position relative to the custom agent prompt and project files explicitly; decide its incognito behavior (§4.10); decide whether it counts toward `calculate_reserved_tokens`. |
| changes the document JSON shape | [[citations]]: citation parsing depends on the exact `document` key and its position. Treat any change here as a citation-reliability change requiring an eval, not a formatting choice. |
| changes the token budget (`backend/onyx/llm/token_budget.py`, `calculate_reserved_tokens`) | SDK compaction thresholds move with the input ceiling; re-check `extract_context_files`'s 60% ceiling still makes sense relative to the new numbers. |
| changes compaction (`agents/compaction.py`) | Branch-aware summary attachment (`parent_message_id`, `last_summarized_message_id`) must still hold across a branched conversation; see `COMPRESSION.md`. |
| touches incognito | `incognito.py:current_turn_persists_content` must still gate every new persisted field; verify against the pinned mode, not the live admin setting. |

---

## 8. How to verify a change

Tests are weak here relative to how much this component matters. A unit test
checks the wiring; it cannot tell you whether the model actually follows an
instruction. **A prompt-text change needs an eval, not a unit test.** See
`backend/onyx/evals/` (`eval.py`, `eval_cli.py`) for the harness. If a change
touches §4.1, §4.2, or §4.5, run the relevant eval suite before and after and
compare instruction-follow rates; do not ship on "it looks fine in one manual
try."

```bash
# Structural / budget-math unit tests
cd backend && uv run pytest tests/unit -k "prompt or token_budget or compression or context"
# Integration tests exercising real assembly through a turn
cd backend && uv run pytest tests/integration -k chat
```

### Manual reproduction

1. Start a long conversation (enough turns to approach the compression
   trigger) inside a project that has files, and attach one file directly to
   an early message.
2. Ask a question the persona's custom instructions (or project instructions)
   should visibly affect. Confirm the instruction is still followed many turns
   in.
3. Ask a question that depends on the project file. Confirm the model still
   references it correctly, even after compression has likely run.
4. Ask a question that depends on the early uploaded file, deep into the
   conversation. Confirm it either still works, or the model explicitly says
   the file is no longer available (forgotten-files notice), never a silent
   wrong answer.
5. Trigger an internal search and confirm the citations that come back resolve
   to real documents, and the model does not narrate citation numbers in its
   prose.

### What "working" looks like

- The custom agent's instructions are still followed after many turns, not
  just the first one.
- Project files are never silently missing; user files are silently missing
  only after truncation, and only with the forgotten-files notice on record.
- Citations resolve correctly and the model never talks about "document 5" or
  "citation_id" in its reasoning text.
- Compression does not visibly lose information the user referenced before it
  ran.

---

## 9. Footguns

- **Moving a single sentence between sections of the system prompt swung
  instruction-follow rates from roughly 30% to 90% in the team's own
  measurement** (`chat/README.md`, "Reasons / Experiments"). Prompt text
  placement is not cosmetic. Do not reorganize prompt text for tidiness,
  alphabetical order, or "cleaner diffs." Any such change needs an eval before
  it merges.
- **Putting custom agent instructions directly into the system prompt is why
  the current design (a separate, moving user message) exists.** The team
  found that custom instructions embedded in the system prompt are poorly
  followed, especially when they are orthogonal or mildly contradictory to the
  base prompt, and that weaker models produce broken tool calls and garbled
  final answers under that arrangement. Do not "simplify" by merging the two.
- **Tool responses become placeholders only in later turns.** Inside one
  turn, every cycle sees the full responses. When a later turn loads saved
  history, ordinary responses turn into `TOOL_CALL_RESPONSE_CROSS_MESSAGE`.
  Tool-call arguments survive. Do not assume a fact from an earlier turn's tool
  response is still visible. Do not remove in-turn responses to save context.
- **Internal search arguments in history are the LLM's original arguments, not
  the expanded queries.** If you are debugging "why did the model re-search,"
  the expanded queries are in the `SearchToolQueriesDelta` packet, not in history.
- **The document `document` key is deliberately not `citation_id` or anything
  resembling a natural-language term**, to keep the model from narrating it.
  Renaming it "for clarity" reintroduces the artifact the naming was chosen to
  avoid.
- **User-uploaded files are allowed to fade out of context.** This is a
  documented product tradeoff, not a bug: dragging every uploaded file forward
  as the conversation grows would degrade quality by stacking irrelevant files
  near the user's actual question. Do not "fix" this without checking
  `chat/README.md`'s "Product considerations" section first.
- **The system prompt and custom agent prompt are recomputed every cycle, not
  once per turn**. Reminder and citation choices depend on completed tools and
  the step limit. File notices depend on the tools available in the current step.
- **`calculate_reserved_tokens` estimates a worst-case system prompt
  (`include_all_guidance=True`)** so the reservation is stable before the
  actual tool set for the turn is known. It will overshoot the real prompt size
  on any turn that does not use every tool; this is intentional slack, not a
  bug to tighten.
