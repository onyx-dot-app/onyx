# Context Assembly

> What the LLM sees on each step of a turn: the system prompt, the per-user
> block, the custom agent prompt, project files, history, file notices and the
> trailing reminder, kept within the token budget by the runtime's compaction. A
> wrong change here rarely raises an error; the answers just get worse.

**Verified against:** `6bac4e012f` (2026-10-29)
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
- **Project files** that fit go into every step as full text and can be cited.
  Project images stay beside project text in the fixed preamble. A project that is too
  large is searched instead ([[projects]]).
- **Long chats** keep working. When a request reaches about 85% of the model's
  usable input, older history is summarized before the model call. Research and
  coding child agents do the same. The user does not see the summary.
- **Admins** edit the default system prompt, which is the default assistant's
  `system_prompt`. An agent can replace the base prompt fully.
- **Images and model switches.** When a chat has images and the user switches
  to a model without vision, the model sees a text marker for each image, not
  the image. With `ENABLE_AZURE_IMAGE_CAP=true`, an Azure model gets at most 50
  images per request: the most recent ones, and a notice of how many were
  dropped. No other provider has a cap.
- **Incognito.** A usage-only session retains questions, text-file messages, image references,
  and full tool results in temporary history
  ([[#usage-only-history-shape]]). Request-only context reaches the current turn
  through its trailing reminder. If the stored conversation expires, a new
  message continues without the earlier messages and with no error
  ([[chat-persistence]]).
- **When it breaks**, users report that the assistant "forgot" a file, ignored
  the agent's instructions, narrated citation numbers, or lost the thread. None
  of these shows a stack trace. When the instructions and the current question
  do not fit the model's window, that model's answer ends with a generic,
  retryable "An unexpected error occurred" message, not a context-limit message
  ([[#fixed-parts-must-fit]]).

---

## Scope

This component owns the content and order of the prompt, the prompt text, the
token reservation, the budget that decides whether project files fit inline,
the file notices, image replay, and what a compaction summary looks like to the
model. The chat agent of [[core-chat-loop]] calls the prompt builders on each
step; that document owns when a step runs.

Neighbours:
- [[agent-runtime]]: when compaction runs, the input budget, truncation and the
  checkpoint rules.
- [[citations]]: the document JSON shape, numbering and the citation guidance
  text.
- [[projects]]: whether project files go inline or through retrieval.
- [[chat-persistence]]: how saved history is rebuilt, the summary rows, and the
  incognito store.
- [[file-store-and-user-files]]: upload, token counts and file lifecycle.
- [[chat-preferences]]: memories, preferences and language.

---

## Architecture

`chat/agent.py:ChatAgent._prepare_step` calls
`chat/prompt_utils.py:build_chat_prompt` to pick the instructions and the
reminder. The runtime then calls `chat/prompt_utils.py:prepare_prompt` on the
working history, after it applies any compaction checkpoint, and again for each
compaction candidate. The list on each model call:

```
[system]                    base prompt, shared user-information framing, tool guidance   stable
[user information]          SYSTEM message: per-user block                                stable
[custom agent prompt]       USER message, fixed before conversation history               stable
[project files and images]  USER message, JSON documents and image content blocks          stable
[conversation summary]      SYSTEM message, when a compaction checkpoint applies          stable
[chronological history]     questions, attachments, assistant messages, full tool results stable
[request-only context]      USER reminder, supplied only for the current request
[oversized-files notice]    USER, names the retrieval tools offered this step
[forgotten-files notice]    USER, files that are not in the working history
[reminder]                  USER, wrapped in <system-reminder>
[image-drop notice]         USER reminder, only when an image cap dropped images
```

The notices and reminders change between steps, so they stay after the stable
prefix. Prompt assembly marks the stable part as cacheable
(`chat/prompt_formatting.py:prepare_model_messages`), and provider-side prefix
caching uses it for supported providers. Unsupported providers use the no-op adapter,
which adds no cache markers. Anthropic breakpoints mark the head, the context before the newest
user message, and the tail. This lets different questions reuse shared files while
tool rounds reuse the growing history. List-valued messages carry their breakpoint
on the final content block so image prefixes reach the provider cache.
Caller markers in the prefix and suffix count toward the four-breakpoint limit.
The adapter preserves them and uses remaining slots for the tail, head, then context.
User-message continuation keeps message markers on separate content blocks so
merging preserves the prefix and suffix cache boundaries.
The OpenAI adapter flags every user
message of the cacheable prefix. On supported OpenAI and Azure API requests
(`llm/prompt_cache/providers/openai.py:uses_explicit_cache_breakpoints`), the LLM
wrapper turns each flag and every tool result into an explicit breakpoint. Later steps
and turns repeat these markers, so they read the entries earlier requests wrote.
Requests with nothing to mark keep implicit caching. `prepare_prompt` copies
the messages it receives and never changes recorded history. Within one step it
replaces a search passage that repeats an earlier result's passage (same
document and text) with a pointer to that result
(`chat/prompt_utils.py:_deduplicate_search_passages`), so a change to the
search result JSON must keep that parse working. Later turns retain saved tool-result
content until compaction or truncation moves the cutoff past it. A placeholder is used when a legacy record has missing or empty output.
Compaction controls history growth; starting a new user turn does not rewrite
previous evidence. A code mode result keeps what a later turn needs in its own
content ([[chat-persistence#code-mode-replay-content]]).
`backend/onyx/chat/README.md` has worked examples of the fixed
preamble and growing history.

**System prompt.** `chat/prompt_utils.py:build_system_prompt` resolves the
`{{CURRENT_DATETIME}}`, `{{CITATION_GUIDANCE}}` and `{{REMINDER_TAG_DESCRIPTION}}`
tags, adds the shared user-information framing and company context, then adds
one guidance section per configured tool. `build_chat_prompt` calls it with
`include_user_info=False` and without `should_cite_documents`. The per-user
block goes into a separate message from `build_user_information_prompt`, so the
system message stays the same for every user. Two callers use
`build_system_prompt`: `build_chat_prompt` for the live prompt, and
`calculate_reserved_tokens` for the token estimate with
`include_all_guidance=True`. A new parameter must reach both, or the
reservation undercounts. A change to the base prompt reaches normal chat turns
and the Slack bot. It does not reach deep research or its research agents, which
write their own system messages in `deep_research/agent.py` and
`deep_research/research_agent.py` with no company context and no agent prompt,
or an agent that replaces the base prompt.

**Tool definitions.** Action preferences keep the full tool definitions and order.
The selected Action appears in a request-only trailing reminder, outside the cached
prefix. When project files replace retrieval, preparation omits an enabled,
configured, allowed Search preference and its reminder. Final steps use `NONE`; providers that cannot enforce it omit definitions.
Those provider exceptions can invalidate cache reuse. The shared policy lives in
`llm/model_capabilities.py` and `llm/multi_llm.py`.

**Custom agent prompt.** `chat/process_message.py:prepare_chat_turn` labels
project and agent instructions when both exist, and tells the model to follow
the agent on a conflict. The default assistant gives no agent instructions. If
`persona.replace_base_system_prompt` is set, the persona's own prompt is the
system message, and the custom agent prompt holds only project instructions. If
the default base prompt is empty, the custom agent prompt becomes the system
message (`build_chat_prompt`).

**Reminder.** `chat/prompt_utils.py:build_chat_reminder` starts from the persona
task prompt, or the open-URL nudge after a web search that found results when
the agent has the open-URL tool and steps remain. The open-URL nudge replaces
the task prompt only when this turn has no image-generation calls. Image
generation does not replace the task prompt, including failed calls and steps
that also search.
`chat/prompt_utils.py:build_reminder_message` then adds the last-step reminder,
the citation guidance when saved history has citation sources, a citeable tool
has run in this turn, or the turn has project files (inline or searched).
Saved sources do not trigger old image, file, or open-URL reminders.
It adds the file reminder after Python makes a file,
and the image reminder when this turn has a result with generated images.
Failed image calls without images do not add the image reminder.
`chat/prompt_formatting.py:prepare_model_messages` wraps it in
`<system-reminder>` tags.

**Budget.** In setup, `calculate_reserved_tokens` reserves a worst-case system
prompt (`include_all_guidance=True`, so it overshoots on purpose), the
replacement and agent prompts, and the files attached to the new message. Then
`chat/files.py:extract_context_files` uses the window that remains, for the
smallest model of the turn, to decide whether project files go inline
([[projects]]). On each model call, the runtime counts the whole assembled
request, tool definitions included, against `agents/compaction.py:context_budget`.
That count uses `cl100k_base` and a fixed estimate per image
(`agents/compaction.py:request_tokens`), not the model's tokenizer. It caps the output with `llm/token_budget.py:resolve_token_budget`
([[agent-runtime]]).

**Compaction.** The runtime summarizes or truncates older history before a model
call ([[agent-runtime]]). The summary reaches the model as a "Conversation
summary" system message after the head, and the history after its cutoff
follows. Summary input replaces attachment text with the file name and ID
(`PromptMetadata.compaction_text`), so facts only in an attachment body survive
only through the forgotten-files notice and a file tool. In a session that keeps
content, `db/chat_response.py` saves a changed summary as a `SUMMARY` row whose
parent is the response where compaction ran. The next turn loads the summary of
the nearest ancestor on its branch (`db/chat.py:find_summary_for_branch`), so a
sibling answer or a branch that forks earlier does not see it. A truncation
fallback saves its cutoff in an empty `SUMMARY` row, so later turns do not
restore the discarded prefix. A content-free incognito session saves no summary
row; its temporary state retains the root checkpoint for later turns.
Regeneration validates the cutoff against the selected history. `chat/COMPRESSION.md` describes the stored form.

**Images in history.** `chat/prompt_formatting.py:prepare_model_messages` runs
on each request. It takes `LLMConfig.supports_images`, or the model catalog when
that is unset. For a model without vision, history images become text markers.
`chat/prompt_formatting.py:resolve_image_cap` sets the Azure cap, and
`prepare_model_messages` then keeps the most recent images and appends a
reminder notice for the dropped images. The cache-prefix estimate (`llm/model_request.py:cache_split_stats`)
counts what is sent, not the stored token counts.

---

## Contracts and traps

1. `reminder-last-head-stable` **The reminder follows everything else, and the
   system prompt stays byte-stable across steps.** Models attend most to the
   last tokens, so per-step guidance (citations, open-URL, last step) goes into
   the reminder. Only the image-drop notice can follow it. The head prompt must
   not change between steps, so the provider prefix cache holds. It must not depend on
   the tool results so far, the tools offered this step or the last-step flag.
   Tool guidance uses the agent's configured tools (`ChatAgent.application_tools`),
   not the step's tools. The date has day precision.
2. `no-citation-guidance-in-system-prompt` **Citation guidance is never in the
   live system prompt.** A `{{CITATION_GUIDANCE}}` tag in the base or agent
   prompt resolves to empty. The same tag in a persona task prompt resolves to
   the guidance once citing applies (saved history has citations, a citeable tool
   ran, or the turn has project files), because the task prompt is in the reminder.
   `include_all_guidance` adds the guidance only for the token estimate.
3. `agent-prompt-separate-message` **The custom agent prompt is a separate user
   message.** With a base prompt, it stays in the fixed preamble before history.
   With no base prompt or base-prompt replacement, it becomes the system message.
   Do not move it ahead of each new question.
4. `reserve-before-extract` **Reserve before you extract.**
   `chat/prompt_utils.py:calculate_reserved_tokens` runs before
   `chat/files.py:extract_context_files` in
   `chat/process_message.py:prepare_chat_turn`. Reverse them and a large project
   takes space the prompt needs.
5. `fixed-parts-must-fit` **The fixed parts must fit, or the response fails.**
   The head prompt, project files, notices, the reminder and the newest
   question and request-only context always stay. Before the first model step,
   the question's attachments also stay. After a tool round, compaction can summarize this
   turn's earlier tool rounds and attachments, and truncation can drop the
   attachments ([[agent-runtime#run-input-protected]]).
   `agents/runtime.py:_truncate_context` raises
   `agents/compaction.py:ContextLimitError` when the rest does not fit. That
   error is a `ValueError`, so `llm/exceptions.py:litellm_exception_to_safe_error`
   reports it as `UNKNOWN_ERROR`, not `CONTEXT_TOO_LONG`. A new large fixed
   element makes this error more frequent.
6. `forgotten-files-need-metadata` **A forgotten-files notice needs file
   metadata.** `chat/process_message.py:prepare_chat_turn` clears the metadata
   map when the persona has no file reader tool. Then a file that compaction or
   truncation removes is not disclosed. With the map, `prepare_prompt` lists
   every attached file whose message is not in the working history.
7. `file-notice-names-offered-tools` **A file notice names only tools the model
   has this step.** `chat/prompt_utils.py:_create_file_tool_metadata_message`
   prefers `read_file`, then internal search, then the Python tool (only when
   every file was staged for it). A notice that names a missing tool makes the
   model guess or search the web.
8. `history-builder-callers` **`chat/prompt_utils.py:prepare_prompt` has
   several callers.** `ChatAgent`, `DeepResearchAgent`, `ResearchAgent` and
   `CodingAgent` call it with their own arguments, such as no custom agent
   prompt. Only `ChatAgent` passes `available_tool_names`, so a deep research
   file notice names no tool. The coding agent's final-step reminder has no
   `is_reminder` flag, so it is sent as a plain user message without the
   `<system-reminder>` wrap. Check all callers after you change the signature or
   order.
9. `replace-base-drops-user-block` **Replacing the base prompt drops the
   per-user block.** With `replace_base_system_prompt`, or with an empty default
   prompt, `build_chat_prompt` builds no user-information message, so memories
   and preferences do not reach the model.
10. `prompt-change-needs-eval` **Prompt wording and position change behaviour a
    lot.** Moving one sentence in the system prompt changed
    instruction-following from about 30% to about 90% (`chat/README.md`,
    "Reasons / Experiments"). A prompt change needs an eval run, not only a unit
    test.
11. `new-context-element-decisions` **Each new context element needs five
    decisions.** Its position relative to the agent prompt and project files,
    whether `calculate_reserved_tokens` counts it, whether it belongs to recorded
    history or request-only prompt assembly, what each incognito mode stores
    ([[chat-persistence#incognito-decision-per-field]]), and whether a resumed
    turn needs it. Add request-only context through `prepare_prompt`, outside recorded
    history. Compaction cutoffs identify recorded messages; they must not reference
    request-only context. A resumed turn rebuilds `ChatAgent` only from
    `chat/models.py:ChatFeatureState` (`chat/restoration.py:restore_chat_agent`),
    not from the current persona or settings. A new prompt input that is not in
    that state, `ChatAgent.capture_state` and `ChatAgent.restore_state` is lost
    on resume or makes the restore fail.
12. `usage-only-history-shape` **A usage-only session retains complete input groups.**
    `chat/history_store.py:RedisChatHistoryStore.prepare_messages` combines
    the selected branch of temporary history with the accepted question and its
    preceding text-file messages ([[chat-persistence]]). Regeneration reuses the
    saved question and attachments. Only new attachments need text extraction;
    earlier text comes from temporary history. Image references
    restore lazy file descriptors; temporary history stores no image bytes.
    Temporary file metadata preserves names and sizes for retrieval notices. The current
    branch and available tools still determine which files a notice can list.
    Full tool results and the compaction checkpoint remain in temporary state.
    Request-only context is supplied separately after stable history and rebuilt
    from feature state for an active run. It is not replayed on later turns.
    If regeneration or storage limits remove a checkpoint's cutoff, the runtime
    discards that checkpoint and budgets the remaining selected history again.

---

## Decisions

- **Caching targets aggregate cost across repeated calls.** Cache writes can
  cost more on a single call; later reads of large prefixes can repay many
  small unused writes. Evaluate token-weighted reads and writes, including
  misses, rather than request counts. The
  [cost model and examples](../../../backend/onyx/llm/prompt_cache/README.md#why-caching-is-always-enabled)
  explain the break-even point and why output length changes the percentage saved.

- **Agent instructions and project files form a fixed preamble.** The earlier
  design moved these blocks toward each new question to improve attention.
  That rewrote the prompt prefix on every user turn. The current design keeps
  the separate user-message role and uses trailing reminders for focused guidance.
  Evaluate long-history instruction following when changing this tradeoff.
- **History retains evidence until compaction.** Automatic tool-result removal
  changed cached prefixes and removed evidence needed for follow-up questions.
  Full results remain available while the runtime manages the context budget.
- **Attached files stay where they were attached.** User attachments remain
  beside their question; project files and images remain in the preamble.
  Changes to project content, configuration, image limits, or a compaction
  checkpoint can intentionally invalidate cache prefixes.

---

## Known issues

- **`COMPRESSION_TRIGGER_RATIO` is a false lead.** `configs/chat_configs.py`
  still reads it, but nothing uses it. The trigger is a constant in
  `agents/compaction.py`. `LOG_ONYX_MODEL_INTERACTIONS` in
  `configs/app_configs.py` is also read but unused, and logs nothing.
- **A context-limit failure looks like an unknown error.** The user sees a
  retryable "unexpected error" when the fixed parts do not fit
  ([[#fixed-parts-must-fit]]).

---

## Dependencies

- [[agent-runtime]]: compaction, the input budget and the step hooks.
- [[agents-personas]]: `system_prompt`, `task_prompt`,
  `replace_base_system_prompt`, `datetime_aware` and persona files.
- [[projects]]: project instructions and the inline-or-retrieval rule.
- [[file-store-and-user-files]]: `UserFile.token_count` and file loading.
- [[chat-preferences]]: memories, preferences and language.
- [[tools-framework]]: configured tools gate guidance sections and file notices.
- [[llm-providers]]: the model sets the window, image support and the tokenizer for setup counts.
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
- `per-cycle-instruction` **A new per-step instruction.** Copy `OPEN_URL_REMINDER`: its text is in
  `prompts/chat_prompts.py` and `build_chat_reminder` picks it. List the
  reminders with `git grep -n "_REMINDER = " backend/onyx/prompts`. Put the
  instruction in the reminder, not in the system prompt
  ([[#reminder-last-head-stable]]).
- `investigate-forgotten-file` **Investigate "the assistant forgot a file" or
  "ignored the instructions".**
  Reproduce in a normal (not incognito) chat with LLM tracing on
  (`backend/AGENTS.md`). The generation span from `tracing/llm_utils.py:llm_generation_span`
  holds the sent messages as `input_messages`. Or set a breakpoint at the
  return of `chat/prompt_utils.py:prepare_prompt`. Check the order in the Architecture diagram, whether a
  forgotten-files notice is present ([[#forgotten-files-need-metadata]]), and
  whether a `SUMMARY` row on the branch covers the turn that held the file.
- `compressed-chat-setup` **Set up a compacted chat for a test.** Copy
  `backend/tests/external_dependency_unit/answer/test_chat_compaction.py`: it
  patches `get_llm_for_persona` with a scripted model, sends a long turn, then
  lowers the model's `max_input_tokens` so the next turn compacts. A `SUMMARY`
  row appears in `chat_message` with its parent on the response. Setting
  `COMPRESSION_TRIGGER_RATIO` does nothing.

---

## Verification

- Unit: `backend/tests/unit/onyx/chat/` covers message order, reminders, prompt
  caching, context files, the organization profile, the user language and
  incognito modes. `backend/tests/unit/onyx/agents/` covers compaction.
- External dependency: `backend/tests/external_dependency_unit/answer/test_chat_compaction.py`
  runs compaction through chat preparation and storage.
- Prompt text or order: run the eval harness in `backend/onyx/evals/` (see its
  README) before and after the change.
- By hand: in a project with files, attach a file to an early message and chat
  until compaction runs. Agent instructions must still apply, project files
  must still be cited, and a question about the early file must get a correct
  answer or a clear "not available", never a wrong answer.
