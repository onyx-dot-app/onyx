# Context Assembly

> The content the LLM actually sees: the system prompt, the custom agent prompt,
> project and user files, the trailing reminder, and the token budget and
> truncation rules that decide what survives a long conversation. Core-chat-loop
> owns the machinery that runs a turn; this component owns what gets fed into it.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE, with query-expansion and search-flow prompt variants in EE
**Owns:**
`backend/onyx/chat/prompt_utils.py`, `token_budget.py`, `compression.py`,
`COMPRESSION.md`, `incognito.py`, `incognito_context.py`,
`backend/onyx/prompts/`, `backend/ee/onyx/prompts/`

**Read first:** `backend/onyx/chat/README.md`. Its "Reasons / Experiments" section
is the rationale behind the ordering and the reminder placement in this document.
The functions that assemble the final message list
(`construct_message_history`, `_build_project_message`,
`_create_context_files_message`, `_create_file_tool_metadata_message`,
`select_reminder_text`) live in `backend/onyx/chat/llm_loop.py`, which
[[core-chat-loop]] owns. This document describes what those functions build and
why; core-chat-loop describes when they run.

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
inside [[core-chat-loop]]'s `run_llm_loop` (`backend/onyx/chat/llm_loop.py`) and
`build_chat_turn` (`backend/onyx/chat/process_message.py`). Two endpoints expose
its token math to the frontend:

| Method | Path | Notes |
|---|---|---|
| GET | `/chat/max-selected-document-tokens` | Upper bound for document selection in the UI. |
| GET | `/chat/available-context-tokens/{id}` | Remaining budget for a session, for the file-upload UI. |

### Environment configuration

| Variable | File | Effect |
|---|---|---|
| `GEN_AI_INPUT_TOKEN_SAFETY_MARGIN` | `configs/model_configs.py` | Fraction of the model's input window held back as safety margin. Shrinks `ChatTokenBudget.input_tokens`. |
| `GEN_AI_NUM_RESERVED_OUTPUT_TOKENS` | `configs/model_configs.py` | Minimum output allowance `ChatTokenBudget.output_allowance` will reserve before it gives up on a cycle. |
| `COMPRESSION_TRIGGER_RATIO` | `configs/chat_configs.py` | Default 0.75. Compress when chat-history tokens exceed this fraction of available space (`compression.py:get_compression_params`). |
| `RECENT_MESSAGES_RATIO` | `compression.py` | Default 0.2. Fraction of the current history tokens kept verbatim (never summarized) when compressing. |
| `DISABLE_VECTOR_DB` | referenced in `process_message.py:extract_context_files` | Changes whether oversized files fall back to search or to `FileReaderTool` metadata. |

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
  (`chat_utils.py:get_custom_agent_prompt`).
- `Memory` rows, surfaced through `db/memory.py:get_memories` into a
  `UserMemoryContext`, feed the "User Information" section of the system prompt
  (`prompt_utils.py:_build_user_information_section`).
- `ChatMessage.last_summarized_message_id` and a summary `ChatMessage` row
  (`parent_message_id` pointing at the branch tip) are how compression persists
  its result. See `COMPRESSION.md` and §4.9.
- `UserFile.token_count`: computed at upload time with the LLM tokenizer (or a
  default fallback tokenizer when the model's is unknown), used by
  `extract_context_files` to decide whether a file fits.

No new tables belong to this component. A schema change here should be treated
as a signal to reconsider the design (see root `CLAUDE.md` on avoiding
migrations).

---

## 4. How it works

### 4.0 The assembled context, annotated

Per cycle, `llm_loop.py:construct_message_history` produces this order:

```
[system]                     -- base prompt + dynamic sections, or persona's own
                                 replacement prompt (§4.1)
[history before last user]   -- truncated oldest-first, budget permitting (§4.6)
[custom agent prompt]        -- USER message, moves here every cycle (§4.2)
[context / project files]    -- JSON document block, moves here every cycle (§4.3-4.4)
[forgotten-files notice]     -- USER message, only if truncation dropped a file (§4.6)
[last user message]          -- untouched, always present
[tool calls and responses]   -- from this turn's cycles so far; responses are
                                 replaced with a placeholder on the *next* cycle (§4.7)
[reminder]                   -- USER_REMINDER message, always last (§4.5)
```

This whole list is rebuilt from scratch on every LLM cycle inside one turn, not
once per turn. A turn that runs three tool cycles calls
`construct_message_history` three times, each with a growing
`[tool calls and responses]` section and a freshly recomputed reminder.

### 4.1 System prompt

`prompt_utils.py:build_system_prompt` assembles the base prompt in this order:

1. The base prompt text, with `{{CURRENT_DATETIME}}`, `{{CITATION_GUIDANCE}}`,
   and `{{REMINDER_TAG_DESCRIPTION}}` placeholders resolved
   (`prompts/prompt_utils.py:apply_prompt_placeholders`). The base prompt itself
   comes from `prompt_utils.py:get_default_base_system_prompt`, which reads the
   default persona's `system_prompt` from the DB, falling back to
   `prompts/chat_prompts.py:DEFAULT_SYSTEM_PROMPT`.
2. `prompt_utils.py:_build_user_information_section`, itself ordered: Basic
   Information, Organization Profile, Team/company context
   (`prompts/prompt_utils.py:get_company_context`), Language, User Preferences,
   Memories.
3. Citation guidance (`prompts/chat_prompts.py:REQUIRE_CITATION_GUIDANCE`, then
   `ANSWER_COVERAGE_GUIDANCE`), only appended if the placeholder wasn't already
   present in the base prompt.
4. Per-tool guidance sections, each gated on that tool actually being offered
   this cycle: search, internal-search, web-search, open-URL, Python, image
   generation, memory (`prompts/tool_prompts.py`). `include_all_guidance=True`
   forces every section on; `calculate_reserved_tokens` uses this to size a
   worst-case prompt up front (§4.8).

If `persona.replace_base_system_prompt` is set, none of this runs. The
persona's own `system_prompt`, run through `prompt_utils.py:process_prompt_template`,
becomes the entire system message, and `custom_agent_prompt_msg` is forced to
`None` (`llm_loop.py:run_llm_loop`, the `if persona and persona.replace_base_system_prompt`
branch).

If the default base prompt is an empty string and no replacement is set, the
custom agent prompt (if any) is promoted to `MessageType.SYSTEM` instead of
`USER`, and stops moving (`llm_loop.py:run_llm_loop`, the trailing `else` branch
under system-prompt handling).

### 4.2 Custom agent prompt

Resolved once per turn by `chat_utils.py:get_custom_agent_prompt(persona, chat_session)`,
before `run_llm_loop` starts (`process_message.py:build_chat_turn`), because the
loop should not need DB access mid-turn. Precedence:

- A non-default persona (`persona.id != DEFAULT_PERSONA_ID`) always wins, even
  inside a project. Its `system_prompt` is the custom agent prompt, unless
  `replace_base_system_prompt` is set, in which case there is no separate
  custom agent prompt (it *is* the system prompt).
- The default persona inside a project falls back to `chat_session.project.instructions`.
- Otherwise there is none.

**A custom persona fully supersedes the project.** This is stated twice in the
source, once in `get_custom_agent_prompt`'s docstring and once in
`process_message.py:resolve_context_user_files`'s: when a custom persona is
active, project files are never loaded, even if the chat is nested in a project.

Inside `run_llm_loop`, unless it has been promoted into the system message
(§4.1), the custom agent prompt is rebuilt every cycle as a
`MessageType.USER` `ChatMessageSimple` and inserted by `construct_message_history`
directly above the last user message, ahead of the project/context files. It
therefore "moves": on turn *N+1* it sits above the turn *N+1* user message, not
where it appeared in turn *N*'s history.

### 4.3 Files: user uploads vs. project files

The two kinds take different load paths, and the product intent differs. The
code preserves it. Project files (and persona-attached files) load through
`process_message.py:extract_context_files`. User uploads do not. Attached files
become history messages in `chat_utils.py:convert_chat_history`, one message per
text file, tagged with `file_id`.

- **User-uploaded files** (attached to a single message) are a "point in time"
  inclusion. They stay where they were uploaded in the message history and, as
  the conversation grows past them, they drift toward the truncation boundary
  like any other old message and can eventually be dropped (with a forgotten-files
  notice, §4.6). This is an accepted tradeoff, not a bug: constantly dragging
  every uploaded file forward would crowd out the actual conversation.
- **Project files** move forward with the conversation every cycle, the same
  way the custom agent prompt does, and `chat/README.md` states outright that
  they must never be dropped from context. They are assumed to be central to
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
(`llm_loop.py:_create_file_tool_metadata_message`).

Project files are additionally always vectorized into the search index
(`chat/README.md`, "Projects"), independent of whether they fit in context, so
a model with a smaller window can RAG over the project instead of losing it.

### 4.4 Document JSON shape

`llm_loop.py:_create_context_files_message` renders in-context files as:

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

Search-tool documents follow the same `document`-keyed shape but arrive as a
`MessageType.TOOL_CALL_RESPONSE` rather than a `MessageType.USER` message; only
project/context files are injected as a user message. All documents surfaced in
one turn collapse into a single message rather than one message per document.

### 4.5 Reminder

`llm_loop.py:select_reminder_text` picks the trailing reminder each cycle, in
priority order: an image-generation reminder if this cycle just ran image gen,
an open-URL nudge if a web search just ran, the open-URL tool is actually
available this cycle, and this is not the last cycle, otherwise `prompt_utils.py:build_reminder_message`, which
merges:

- The user-configured persona task prompt (`persona.task_prompt`), if any.
- `prompts/chat_prompts.py:LAST_CYCLE_CITATION_REMINDER`, appended only on the
  final cycle (`out_of_cycles`).
- `prompts/chat_prompts.py:CITATION_REMINDER` followed by
  `ANSWER_COMPLETENESS_REMINDER`, appended whenever a search-like tool has run
  this turn (`should_cite_documents or always_cite_documents`) and kept on every
  subsequent cycle until the turn ends, not just the cycle the search ran in.
- `prompts/chat_prompts.py:FILE_REMINDER`, appended when the Python tool
  generated a file this turn.

The result is one `MessageType.USER_REMINDER` message, appended last by
`construct_message_history` regardless of anything else in the list. There is
no code path that appends anything after it.

### 4.6 Truncation and the forgotten-files notice

`construct_message_history` reserves tokens for the system prompt, custom agent
prompt, project/context-file messages, and the reminder first, then fits
history before the last user message into whatever remains, walking it
**newest-first** (`for msg in reversed(history_before_last_user)`) until a
message would overflow the remaining budget, then stops: everything older is
dropped.

If any dropped message carries a `file_id`, or if `all_injected_file_metadata`
contains a `file_id` no surviving message carries (orphaned by prior summary
truncation), `_create_file_tool_metadata_message` builds a forgotten-files
notice naming those files. The notice is reserved out of the same budget and
inserted right before the last user message. If reserving space for that notice
itself pushes the budget negative, the loop evicts additional history messages
(oldest of the kept set first) until it fits, and folds any newly evicted file
into the notice.

The notice is conditional. It needs a non-empty `all_injected_file_metadata` and
a `token_counter`. `process_message.py` passes an empty metadata map when the
turn has no FileReader tool, so a dropped file is then not disclosed. The
budget check also has a gap. The loop rebuilds the notice for each newly
evicted file but does not subtract the extra tokens from `remaining_budget`.
The final history can exceed `available_tokens` by that difference.

`_drop_orphaned_tool_call_responses` runs last, stripping any
`TOOL_CALL_RESPONSE` whose matching `ASSISTANT` tool-call message got truncated
out from under it (some providers reject a response with no matching call).

### 4.7 Tool calls in history

Tool call *arguments* survive truncation; tool call *responses* do not.
`llm_step.py` (owned by [[core-chat-loop]]) is where responses get replaced
with a fixed placeholder string once a cycle completes; this component only
carries the resulting messages through `construct_message_history` unchanged.
For the internal search tool specifically, the arguments kept in history are
the **expanded** queries the tool actually ran (see EE query expansion,
`backend/ee/onyx/prompts/query_expansion.py`), not the raw query text the LLM
wrote, so a later cycle sees what was actually searched.

### 4.8 Token budget

`token_budget.py:resolve_chat_token_budget(llm)` builds a `ChatTokenBudget`:
`input_tokens` is the model's `max_input_tokens` shrunk by
`GEN_AI_INPUT_TOKEN_SAFETY_MARGIN`, and `output_allowance` refuses to grant an
output budget smaller than `GEN_AI_NUM_RESERVED_OUTPUT_TOKENS` once estimated
input is subtracted.

Before any of this runs, `prompt_utils.py:calculate_reserved_tokens` is called
once per turn (`process_message.py:build_chat_turn`) to reserve space for the
system prompt (worst case, via `include_all_guidance=True`) plus the custom
agent prompt plus attached-file tokens, computed against the
placeholder-substituted final text so a long directory-profile value cannot
invalidate the reservation after the fact. This reservation must happen before
`extract_context_files` decides whether project files fit (§4.3): reversing
that order would let files claim space the prompt still needs.

Inside `run_llm_loop`, `available_tokens` is further reduced per cycle by
`compute_all_tool_tokens(final_tools, token_counter)` before
`construct_message_history` is called, since tool definitions themselves
consume input tokens.

### 4.9 Compression

After a turn's completion is persisted, exactly one model's completion (in a
multi-model turn) "claims" compression via a `compression_claimed` flag
([[core-chat-loop]], `process_message.py`) and calls
`compression.py:compress_chat_history` if
`compression.py:get_compression_params(...).should_compress` is true.
`get_compression_params` triggers when
`calculate_total_history_tokens(chat_history) > available_tokens * COMPRESSION_TRIGGER_RATIO`
(default 0.75). `compress_chat_history` then:

1. Finds an existing summary for this branch (`find_summary_for_branch`,
   walking `parent_message_id` membership).
2. Splits history at a token boundary via `get_messages_to_summarize`, keeping
   the most recent `RECENT_MESSAGES_RATIO` (default 0.2) of the current history
   tokens verbatim.
3. Summarizes everything older, folding in any prior summary text so
   information does not disappear across repeated compressions
   (`COMPRESSION.md`, "Progressive Summarization").
4. Saves the result as a new `ChatMessage` attached to the branch tip
   (`parent_message_id`) with `last_summarized_message_id` pointing at the
   cutoff, rather than rewriting the summarized message itself, so the summary
   never leaks into sibling branches that share history up to that point.

Multi-model turns use the smallest context window across all selected models
for this math, matching `llm_max_context_window` in `extract_context_files`.

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
`incognito_context.py:append_incognito_message`).

### Worked examples (from `chat/README.md`)

Custom agent, no files. `CA` moves to sit above each new user message, and the
reminder appears only once a tool has run:

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

1. **The reminder message is always last.** Nothing may be appended after it.
   Models attend most strongly to trailing tokens; this is why citation
   reliability lives here.
2. **The custom agent prompt is a `MessageType.USER` message, not part of the
   system prompt, unless it has replaced the system prompt outright.** It moves
   every cycle to sit directly above the last user message. If
   `persona.replace_base_system_prompt` is set, it becomes the system message
   and stops moving.
3. **Project files are never dropped from context.** Only user-uploaded files
   drift out under truncation pressure.
4. **User-uploaded files do not move.** They stay attached to the point in the
   history where they were uploaded and drift toward truncation like any other
   old message; this is intentional, not a bug to fix.
5. **Truncation is oldest-first and must emit a forgotten-files notice for a
   dropped file whenever file metadata is available (FileReader tool present).**
   A truncation path that drops a `file_id` without updating
   `all_injected_file_metadata` and running `_create_file_tool_metadata_message`
   silently lies to the model.
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
   once per turn.** Code that caches either across cycles inside one turn will
   go stale the moment `should_cite_documents` or the active tool set changes
   mid-turn.

---

## 6. Relationships

**Depends on**
- [[agents-personas]]: persona fields (`system_prompt`, `task_prompt`,
  `replace_base_system_prompt`, `datetime_aware`, `user_files`) drive nearly
  every branch in §4.1-4.3.
- [[projects]]: `Project.instructions` and project files are a source of both
  the custom agent prompt and the project-files section.
- [[file-store-and-user-files]]: upload-time tokenization and file loading
  (`load_in_memory_chat_files`) that `extract_context_files` consumes.
- [[chat-preferences]]: user memories, preferences, and language settings
  feeding `_build_user_information_section`.
- [[tools-framework]]: which tools are offered this cycle gates the system
  prompt's tool-guidance sections and the forgotten-files notice's tool name.
- [[llm-providers]]: `llm.config.max_input_tokens` and tokenizer resolution
  drive the entire token budget.

**Depended on by**
- [[core-chat-loop]]: `run_llm_loop` calls every function in this component on
  every cycle; it is the sole caller.
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
| changes the token budget (`token_budget.py`, `calculate_reserved_tokens`) | Compression triggers (`get_compression_params`) move with the available-token math; re-check `extract_context_files`'s 60% ceiling still makes sense relative to the new numbers. |
| changes compression (`compression.py`) | Branch-aware summary attachment (`parent_message_id`, `last_summarized_message_id`) must still hold across a branched conversation; see `COMPRESSION.md`. |
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
- **Tool responses are discarded from history and replaced with a placeholder.**
  Only tool-call arguments survive a cycle boundary. Anything a later cycle
  needs must be re-derivable from the arguments or re-fetched; do not assume a
  fact from an earlier tool response is still visible.
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
  once per turn**, because `should_cite_documents`, the active tool set, and
  `out_of_cycles` all change mid-turn. Any refactor that hoists them out of the
  cycle loop will serve stale guidance on later cycles.
- **`calculate_reserved_tokens` estimates a worst-case system prompt
  (`include_all_guidance=True`)** so the reservation is stable before the
  actual tool set for the turn is known. It will overshoot the real prompt size
  on any turn that does not use every tool; this is intentional slack, not a
  bug to tighten.
