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
  A project that is too large is searched instead ([[projects]]).
- **Long chats** keep working. When a request reaches about 85% of the model's
  usable input, older history is summarized before the model call. Research and
  coding child agents do the same. The user does not see the summary.
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
  of these shows a stack trace. When the instructions and the current question
  with its attachments do not fit the model's window, that model's answer ends
  with a context-limit error ([[#fixed-parts-must-fit]]).

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
[system]                    base prompt, shared user-information framing, tool guidance   cached
[user information]          SYSTEM message: per-user block                                cached
[conversation summary]      SYSTEM message, when a compaction checkpoint applies          cached
[history before last user]  includes the newest message's file and request-context messages cached
[custom agent prompt]       USER message, placed above the newest user message            cached
[project files]             USER message, JSON documents                                  cached
[last user message]                                                                       cached
[this turn's tool calls and responses]                                                    cached
[oversized-files notice]    USER, names the retrieval tools offered this step
[forgotten-files notice]    USER, files that are not in the working history
[reminder]                  USER, wrapped in <system-reminder>
[image-drop notice]         USER reminder, only when an image cap dropped images
```

The notices and reminders change between steps, so they stay after the cached
prefix. `prepare_prompt` copies the messages it receives and never changes
recorded history. On a later turn, saved tool results carry
`omit_tool_result_content` (`chat/chat_utils.py:omit_prior_tool_result_content`),
and `prepare_prompt` sends `TOOL_CALL_RESPONSE_CROSS_MESSAGE` in their place.
Image generation results stay visible. `backend/onyx/chat/README.md` has worked
examples of how the agent prompt and project files move from turn to turn.

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

**Custom agent prompt.** `chat/process_message.py:prepare_chat_turn` labels
project and agent instructions when both exist, and tells the model to follow
the agent on a conflict. The default assistant gives no agent instructions. If
`persona.replace_base_system_prompt` is set, the persona's own prompt is the
system message, and the custom agent prompt holds only project instructions. If
the default base prompt is empty, the custom agent prompt becomes the system
message and stops moving (`build_chat_prompt`).

**Reminder.** `chat/prompt_utils.py:build_chat_reminder` starts from the image
generation reminder, the open-URL nudge (after a web search in the previous step
that found results, when the agent has the open-URL tool and steps remain) or
the persona task prompt. Only one of the three is used, so the task prompt is
left out of a step that gets the image or open-URL reminder.
`chat/prompt_utils.py:build_reminder_message` then adds the last-step reminder,
the citation guidance once a citeable tool has run in this turn or the turn has
project files (inline or searched), and the file reminder after the Python tool
makes a file. `chat/prompt_formatting.py:prepare_model_messages` wraps it in
`<system-reminder>` tags.

**Budget.** In setup, `calculate_reserved_tokens` reserves a worst-case system
prompt (`include_all_guidance=True`, so it overshoots on purpose), the
replacement and agent prompts, and the files attached to the new message. Then
`chat/files.py:extract_context_files` uses the window that remains, for the
smallest model of the turn, to decide whether project files go inline
([[projects]]). On each model call, the runtime counts the whole assembled
request, tool definitions included, against `agents/compaction.py:context_budget`,
and caps the output with `llm/token_budget.py:resolve_token_budget`
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
sibling answer or a branch that forks earlier does not see it. A content-free
incognito session saves no summary row. `chat/COMPRESSION.md` describes the
stored form.

**Images in history.** `chat/prompt_formatting.py:prepare_model_messages` runs
on each request. It takes `LLMConfig.supports_images`, or the model catalog when
that is unset. For a model without vision, history images become text markers.
`chat/prompt_formatting.py:resolve_image_cap` keeps only the most recent images
when a provider cap applies, and appends a reminder notice for the dropped
images. The cache-prefix estimate (`llm/model_request.py:cache_split_stats`)
counts what is sent, not the stored token counts.

---

## Contracts and traps

1. `reminder-last-head-stable` **The reminder follows everything else, and the
   system prompt stays byte-stable across steps.** Models attend most to the
   last tokens, so per-step guidance (citations, open-URL, last step) goes into
   the reminder. Only the image-drop notice can follow it. The head prompt must
   not change between steps, so the prompt cache holds. It must not depend on
   the tool results so far, the tools offered this step or the last-step flag.
   Tool guidance uses the agent's configured tools (`ChatAgent.application_tools`),
   not the step's tools. The date has day precision.
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
   `chat/process_message.py:prepare_chat_turn`. Reverse them and a large project
   takes space the prompt needs.
5. `fixed-parts-must-fit` **The fixed parts must fit, or the response fails.**
   `agents/runtime.py:_truncate_context` raises `ContextLimitError` when the
   system messages and the current turn do not fit, including the head prompt,
   project files, notices, the reminder, the newest question with its
   attachments and request context, and this turn's tool rounds. Only older
   turns are summarized or dropped, at boundaries that keep a tool call with
   its result ([[agent-runtime#run-input-protected]]). A new large fixed element
   makes this error more frequent.
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
   prompt. Check them after you change its signature or order.
9. `replace-base-drops-user-block` **Replacing the base prompt drops the
   per-user block.** With `replace_base_system_prompt`, or with an empty default
   prompt, `build_chat_prompt` builds no user-information message, so memories
   and preferences do not reach the model.
10. `prompt-change-needs-eval` **Prompt wording and position change behaviour a
    lot.** Moving one sentence in the system prompt changed
    instruction-following from about 30% to about 90% (`chat/README.md`,
    "Reasons / Experiments"). A prompt change needs an eval run, not only a unit
    test.
11. `new-context-element-decisions` **Each new context element needs four
    decisions.** Its position relative to the agent prompt and project files,
    whether `calculate_reserved_tokens` counts it, whether it is request-only
    (then set `allow_compaction_cutoff=False`,
    [[agent-runtime#stable-message-ids]]), and what each incognito mode stores
    ([[chat-persistence#incognito-decision-per-field]]).

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

- **`chat/README.md` is out of date.** It says citation guidance and per-cycle
  tool descriptions go into the system prompt
  ([[#no-citation-guidance-in-system-prompt]], [[#reminder-last-head-stable]]).
  Its document example does not match the code ([[citations#document-key-prompt-design]]),
  and it names a file, chat/llm_loop.py, that does not exist. The function it
  names there is in `chat/prompt_utils.py:_create_context_files_message`.
- **`COMPRESSION_TRIGGER_RATIO` is a false lead.** `configs/chat_configs.py`
  still reads it, but nothing uses it. The trigger is a constant in
  `agents/compaction.py`.

---

## Dependencies

- [[agent-runtime]]: compaction, the input budget and the step hooks.
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
- `per-cycle-instruction` **A new per-step instruction.** Copy `OPEN_URL_REMINDER`: its text is in
  `prompts/chat_prompts.py` and `build_chat_reminder` picks it. List the
  reminders with `git grep -n "_REMINDER = " backend/onyx/prompts`. Put the
  instruction in the reminder, not in the system prompt
  ([[#reminder-last-head-stable]]).
- `investigate-forgotten-file` **Investigate "the assistant forgot a file" or
  "ignored the instructions".**
  Set `LOG_ONYX_MODEL_INTERACTIONS=true` and reproduce in a normal (not
  incognito) chat. `backend/log/api_server_debug.log` then shows the message
  list for each inference. Check the order in the Architecture diagram, whether a
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
