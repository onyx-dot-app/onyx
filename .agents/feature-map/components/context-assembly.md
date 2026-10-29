# Context Assembly

> What the LLM sees on each cycle of a turn: the system prompt, the per-user
> block, the custom agent prompt, project files, history, file notices and the
> trailing reminder, kept within the token budget by truncation and history
> compression. A wrong change here rarely raises an error; the answers just get
> worse.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

- **Custom agent instructions** apply for the whole chat, not only the first
  few turns. Inside a project, the project instructions also apply. When the two
  conflict, the agent instructions win.
- **Personal context.** The assistant knows the user's name, email, role,
  directory profile, preferred language, preferences and memories. An agent
  author can write `{{user.<key>}}` in an agent prompt, and each user sees their
  own value. A known key with no value becomes empty text. An unknown key stays
  as written, so the author can see the typo.
- **Files attached to one message** are part of the chat at that point. In a
  long chat they can drop out of the prompt. If the agent has the file reader
  tool, the model is told which files it lost and how to read them. Without it,
  the model is not told ([[#forgotten-files-need-metadata]]).
- **Project files** that fit go into every cycle as full text and can be cited.
  A project that is too large is searched instead ([[projects]]).
- **Long chats** keep working. After a turn passes about 75% of the usable
  window, older messages are summarized. The user does not see the summary.
- **Admins** edit the default system prompt, which is the default assistant's
  `system_prompt`. An agent can replace the base prompt fully.
- **Images and model switches.** When a chat has images and the user switches
  to a model without vision, the model sees a text marker for each image, not
  the image. When a provider image cap applies, the model sees only the most
  recent images and a notice of how many were dropped.
- **Incognito.** In a usage-only session, if the stored conversation expires,
  the next turn continues without the earlier messages and with no error
  ([[chat-persistence]]).
- **When it breaks**, users report that the assistant "forgot" a file, ignored
  the agent's instructions, narrated citation numbers, or lost the thread. None
  of these shows a stack trace. When the fixed parts of the prompt do not fit the
  model's window, that model's answer ends with a "Not enough tokens" error
  ([[#fixed-parts-must-fit]]).

---

## Scope

This component owns the content and order of the prompt, the prompt text, the
token budget and reservation, the budget that decides whether project files fit
inline, the file notices, and history compression. The assembly functions
(`construct_message_history`, `select_reminder_text`,
`_create_context_files_message`, `_create_file_tool_metadata_message`) sit in
the loop module that [[core-chat-loop]] owns. This document owns what they
build. That document owns when they run.

Neighbours:
- [[citations]]: the document JSON shape, numbering and the citation guidance
  text.
- [[projects]]: whether project files go inline or through retrieval.
- [[chat-persistence]]: how saved history is rebuilt, including the placeholder
  that replaces tool responses from earlier turns, and the incognito store.
- [[file-store-and-user-files]]: upload, token counts and file lifecycle.
- [[chat-preferences]]: memories, preferences and language.
- [[agent-runtime]]: a second history formatter that is not wired.

---

## Architecture

`run_llm_loop` rebuilds the whole list on every cycle:

```
[system]                    base prompt, shared user-information framing, tool guidance   cached
[user information]          SYSTEM message: per-user block                                cached
[history before last user]  newest first until the budget ends; older messages drop       cached
[custom agent prompt]       USER message, placed above the newest user message            cached
[project files]             USER message, JSON documents                                  cached
[last user message]                                                                       cached
[this turn's tool calls and responses]                                                    cached
[oversized-files notice]    USER, names the retrieval tools offered this cycle
[forgotten-files notice]    USER, files that truncation or a summary removed
[reminder]                  USER_REMINDER, always last
```

The notices and the reminder change between cycles, so they stay after the
cached prefix. `backend/onyx/chat/README.md` has worked examples of how the agent
prompt and project files move from turn to turn.

**System prompt.** `chat/prompt_utils.py:build_system_prompt` resolves the
`{{CURRENT_DATETIME}}`, `{{CITATION_GUIDANCE}}` and `{{REMINDER_TAG_DESCRIPTION}}`
tags, adds the shared user-information framing and company context, then adds
one guidance section per configured tool. The live loop calls it with
`include_user_info=False` and without `should_cite_documents`. The per-user
block goes into a separate message from `build_user_information_prompt`, so the
system message stays the same for every user. Two callers use
`build_system_prompt`: `run_llm_loop` for the live prompt, and
`calculate_reserved_tokens` for the token estimate with
`include_all_guidance=True`. A new parameter must reach both, or the
reservation undercounts. A change to the base prompt reaches normal chat turns
and the Slack bot. It does not reach deep research, which writes its own system
messages in `deep_research/dr_loop.py` with no company context and no agent
prompt, or an agent that replaces the base prompt.

**Custom agent prompt.** `chat/chat_utils.py:get_custom_agent_prompt` labels
project and agent instructions when both exist, and tells the model to follow
the agent on a conflict. The default assistant gives no agent instructions. If
`persona.replace_base_system_prompt` is set, the persona's own prompt is the
system message, and the custom agent prompt holds only project instructions. If
the default base prompt is empty, the custom agent prompt becomes the system
message and stops moving.

**Reminder.** `chat/llm_loop.py:select_reminder_text` starts from the image
generation reminder, the open-URL nudge (after a web search that found
results, when the agent has the open-URL tool and cycles remain) or the persona
task prompt. Only one of the three is used, so the task prompt is left out of a
cycle that gets the image or open-URL reminder.
`chat/prompt_utils.py:build_reminder_message` then adds the last-cycle reminder,
the citation guidance once a citeable tool has run or the turn has project files
(inline or searched), and the file reminder after the Python tool makes a file.

**Budget.** In setup, `calculate_reserved_tokens` reserves a worst-case system
prompt (`include_all_guidance=True`, so it overshoots on purpose), the
replacement and agent prompts, and the files attached to the new message. Then
`chat/files.py:extract_context_files` uses the window that remains, for the
smallest model of the turn, to decide whether project files go inline
([[projects]]). In each cycle, the loop takes
`resolve_token_budget(llm).input_tokens`, subtracts the tool definitions, and
passes the rest to `construct_message_history`.

**Compression.** After a turn is saved, `chat/compression.py:get_compression_params`
compares the next turn's history with `COMPRESSION_TRIGGER_RATIO` of the window
left after the reservation. `compress_chat_history` summarizes the older part,
keeps the newest `RECENT_MESSAGES_RATIO` of tokens verbatim, and folds in the
previous summary. It saves the summary as a `SUMMARY` row whose parent is the
last user message of the chain
(`chat/compression.py:get_summary_parent_message_id`). All answers to that
message, such as multi-model answers and regenerations, share the summary. A
branch that forks earlier does not see it. The next turn loads it with
`load_branch_summary`, drops the messages it covers, and puts it first as an
assistant message. An incognito session that does not keep content skips
compression, because a summary is a saved content row.

**Images in history.** `chat/llm_step.py:_resolve_history_image_replay` runs
before each inference. It takes `LLMConfig.supports_images`, or the model
catalog when that is unset. For a model without vision, history images become
text markers. `chat/llm_step.py:resolve_image_cap` keeps only the most recent
images when a provider cap applies, and the dropped images add a reminder
notice. The cache-prefix estimate (`_cache_split_stats`) counts what is sent,
not the stored token counts.

---

## Contracts and traps

1. `reminder-last-head-stable` **The reminder is the last message, and the
   system prompt stays byte-stable across cycles.** Models attend most to the
   last tokens, so per-cycle guidance (citations, open-URL, last cycle) goes into
   the reminder. The head prompt must not change between cycles, so the prompt
   cache holds. It must not depend on `should_cite_documents`, the tools offered
   this cycle or `out_of_cycles`. Tool guidance uses the turn's configured tools,
   not `final_tools`. The date has day precision.
2. `no-citation-guidance-in-system-prompt` **Citation guidance is never in the
   live system prompt.** A `{{CITATION_GUIDANCE}}` tag in the base or agent
   prompt resolves to empty. The same tag in a persona task prompt resolves to
   the guidance once citing applies (a citeable tool ran, or the turn has
   project files), because the task prompt is in the reminder.
   `include_all_guidance` adds the guidance only for the token estimate.
3. `agent-prompt-separate-message` **The custom agent prompt is a separate user
   message.** It moves to sit just above the newest user message. Do not merge it
   into the system prompt.
4. `reserve-before-extract` **Reserve before you extract.**
   `chat/prompt_utils.py:calculate_reserved_tokens` runs before
   `chat/files.py:extract_context_files` in
   `chat/process_message.py:build_chat_turn`. Reverse them and a large project
   takes space the prompt needs.
5. `fixed-parts-must-fit` **The fixed parts must fit, or the turn fails.**
   `chat/llm_loop.py:construct_message_history` raises `ValueError` when the
   system prompt, user block, agent prompt, project files, oversized-files
   notice and reminder exceed the budget, or when the last user message and this
   turn's tool rounds do not fit. Only older history is trimmed. Then
   `chat/llm_loop.py:_drop_orphaned_tool_call_responses` removes responses
   whose call was trimmed, because some providers reject them.
6. `forgotten-files-need-metadata` **A forgotten-files notice needs file
   metadata.** `chat/process_message.py:build_chat_turn` passes an empty map
   when the persona has no file reader tool. Then a file dropped by truncation
   is not disclosed. Files removed by a summary are always listed.
7. `file-notice-names-offered-tools` **A file notice names only tools the model
   has this cycle.** `chat/llm_loop.py:_create_file_tool_metadata_message`
   prefers `read_file`, then internal search, then the Python tool (only when
   every file was staged for it). A notice that names a missing tool makes the
   model guess or search the web.
8. `history-builder-callers` **`chat/llm_loop.py:construct_message_history`
   has several callers.** Deep research, the research agent and the coding
   agent call it with their own arguments, such as `last_n_user_messages`.
   Check them after you change its signature or order.
9. `replace-base-drops-user-block` **Replacing the base prompt drops the
   per-user block.** With `replace_base_system_prompt`, or with an empty default
   prompt, the loop builds no user-information message, so memories and
   preferences do not reach the model.
10. `prompt-change-needs-eval` **Prompt wording and position change behaviour a
    lot.** Moving one sentence in the system prompt changed
    instruction-following from about 30% to about 90% (`chat/README.md`,
    "Reasons / Experiments"). A prompt change needs an eval run, not only a unit
    test.
11. `new-context-element-decisions` **Each new context element needs three
    decisions.** Its position relative to the agent prompt and project files,
    whether `calculate_reserved_tokens` counts it, and what each incognito mode
    stores ([[chat-persistence#incognito-decision-per-field]]).

---

## Decisions

- **Agent instructions are a moving user message.** In the system prompt they
  were followed poorly, conflicted with the base prompt, and made weaker models
  produce broken tool calls. A fixed position fades as the chat grows
  (`chat/README.md`).
- **Attached files stay where they were attached.** Moving every file forward
  would crowd out the question. Project files move forward, because the user
  works from them (`chat/README.md`, "Product considerations").

---

## Known issues

- **The forgotten-files budget can overrun.** When eviction adds a file to the
  notice, `construct_message_history` rebuilds the notice but does not subtract
  the added tokens. The history can exceed the budget by that amount.
- **`chat/README.md` is out of date.** It says citation guidance and per-cycle
  tool descriptions go into the system prompt
  ([[#no-citation-guidance-in-system-prompt]], [[#reminder-last-head-stable]]).
  Its document example does not match the code ([[citations#document-key-prompt-design]]).
- **The compression docs name the wrong summary parent.** The module docstring
  of `chat/compression.py` and `chat/COMPRESSION.md` say the parent is the last
  message. `get_summary_parent_message_id` uses the last user message.

---

## Dependencies

- [[agents-personas]]: `system_prompt`, `task_prompt`,
  `replace_base_system_prompt`, `datetime_aware` and persona files.
- [[projects]]: project instructions and the inline-or-retrieval rule.
- [[file-store-and-user-files]]: `UserFile.token_count` and file loading.
- [[chat-preferences]]: memories, preferences and language.
- [[tools-framework]]: configured tools gate guidance sections and file notices.
- [[llm-providers]]: the model sets the window, the tokenizer and image support.
- [[chat-persistence]]: saved history and summary rows.

---

## Recipes

- `tool-guidance-section` **A new tool guidance section.** Copy the memory tool: `MEMORY_GUIDANCE` in
  `prompts/tool_prompts.py` appears twice in `build_system_prompt`. Add the new
  text to both places. The `include_all_guidance` branch returns early with its
  own list of every section, and only that list reaches the reservation. The
  `has_memory` branch keys the live prompt on the configured tools. List the
  current sections with `git grep -n "_GUIDANCE" backend/onyx/chat/prompt_utils.py`.
- `workspace-setting-in-prompt` **A workspace setting in the system prompt.** Copy the company name and
  description: `prompts/prompt_utils.py:get_company_context` reads them from
  `Settings`, and `build_system_prompt` appends the result. Read the setting
  inside `build_system_prompt`, as that function does, so both callers get it
  and the reservation stays right. A workspace value is the same for every
  user, so it belongs in the system prompt; a per-user value goes in the
  user-information message. The text does not reach deep research or an agent
  that replaces the base prompt. Run an eval ([[#prompt-change-needs-eval]]).
  The `Settings` field itself is [[chat-preferences#new-workspace-option]].
- `per-cycle-instruction` **A new per-cycle instruction.** Copy `OPEN_URL_REMINDER`: its text is in
  `prompts/chat_prompts.py` and `select_reminder_text` picks it. List the
  reminders with `git grep -n "_REMINDER = " backend/onyx/prompts`. Put the
  instruction in the reminder, not in the system prompt
  ([[#reminder-last-head-stable]]).
- `investigate-forgotten-file` **Investigate "the assistant forgot a file" or
  "ignored the instructions".**
  Set `LOG_ONYX_MODEL_INTERACTIONS=true` and reproduce in a normal (not
  incognito) chat. `backend/log/api_server_debug.log` then shows the message
  list for each inference. Check the order in the Architecture diagram, whether a
  forgotten-files notice is present ([[#forgotten-files-need-metadata]]), and
  whether a `SUMMARY` row covers the turn that held the file.
- `compressed-chat-setup` **Set up a compressed chat for a test.** Set `COMPRESSION_TRIGGER_RATIO` low
  (for example `0.05`), restart the API server, because the value is read at
  import, and send a few turns. A `SUMMARY` row appears in
  `chat_message` with its parent on the last user message.

---

## Verification

- Unit: `backend/tests/unit/onyx/chat/` covers message order, compression,
  context files, the organization profile, the user language and incognito
  modes.
- Prompt text or order: run the eval harness in `backend/onyx/evals/` (see its
  README) before and after the change.
- By hand: in a project with files, attach a file to an early message and chat
  until compression runs. Agent instructions must still apply, project files
  must still be cited, and a question about the early file must get a correct
  answer or a clear "not available", never a wrong answer.
