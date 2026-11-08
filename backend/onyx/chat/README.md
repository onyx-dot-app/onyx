# Overview of Context Management

This document reviews some design decisions around the main agent-loop powering Onyx's chat flow.
It is highly recommended for all engineers contributing to this flow to be familiar with the concepts here.

> Note: it is assumed the reader is familiar with the Onyx product and features such as Projects, User files, Citations, etc. 

## System Prompt

The system prompt is a default prompt that comes packaged with the system. Users can edit the default prompt and it will be persisted in the database.

Some parts of the system prompt are filled in when the turn starts:

- The date and time, when the prompt is datetime-aware
- When to use each tool, for the tools available in the turn

The system prompt does not change between the steps of a turn, so the provider's prompt cache holds. Guidance that
depends on the step, such as how to cite the documents a tool returned, goes into the reminder message at the end of
the context instead (see "Reminders").

## Custom Agent Prompt

The custom agent instructions are a separate user message in the fixed preamble, before project files and chronological history.
They stay in the same position as the conversation grows. If the agent replaces the base system prompt, its system instructions
use the system-message role; project instructions remain a separate user message.

## How Files are handled

On upload, Files are processed for tokens, if too many tokens to fit in the context, it’s considered a failed inclusion. This is done using the LLM tokenizer.

- In many cases, there is not a known tokenizer for each LLM so there is a default tokenizer used as a catchall.
- File upload happens in 2 parts - the actual upload + token counting.
- Files are added into chat context as a “point in time” inclusion and move up the context window as the conversation progresses.
  Every file knows how many tokens it is (model agnostic), image files have some assumed number of tokens.

User-uploaded images stay attached to their original user messages. Project images belong to the fixed project preamble.
Usage-only temporary chats retain each question with its text-file messages and image references.
Follow-up requests and regeneration use the same saved attachments until compaction or temporary-history limits remove them.

**Future Extension**:
Files selected from the search results are also counted as “point in time” inclusions. Files that are too large cannot be selected.
For these files, the "entire file" does not exist for most connectors, it's pieced back together from the search engine.

## Projects

When project files fit in the model context, their text and images form a fixed preamble before conversation history.
They remain available after history compaction. New user turns do not move them or attach them to the newest question.
Changing project contents can change the preamble and invalidate the cached prefix.
Project files are vectorized and stored in the Search Engine so that if the user chooses a model with less context than the number of tokens in the project,
the system can RAG over the project files.

## How documents are represented

Documents from search or uploaded Project files are represented as a json so that the LLM can easily understand it.

Project files go in a user message with a prefix string to make the context clearer to the LLM
(`chat/prompt_utils.py:_create_context_files_message`):

```
Here are some documents provided for context, they may not all be relevant:
{
    "documents": [
        {"document": 1, "title": "Hello", "contents": "Foo"},
        {"document": 2, "title": "World", "contents": "Bar"}
    ]
}
```

Search results (web or internal) go in a Tool Call response with no prefix
(`tools/tool_implementations/utils.py:convert_inference_sections_to_llm_string`). They use a `"results"` wrapper,
the `content` key, and an optional JSON-string `metadata` field after `content`.

Documents are represented with the `document` key so that the LLM can easily cite them with a single number. The tool returns have to be richer to be able to
translate this into links and other UI elements. What the LLM sees is far simpler to reduce noise/hallucinations.

Note that documents included in a single turn should be collapsed into a single user message.

Search tools also give URLs to the LLM so that open_url (a separate tool) can be called on them.

## Reminders

To ensure the LLM follows certain specific instructions, instructions are added at the very end of the chat context as a user message. If a search related
tool is used, a citation reminder is always added. Otherwise, by default there is no reminder. If the user configures reminders, those are added to the
final message. If a search related tool just ran and the user has reminders, both appear in a single message.

If a search related tool is called at any point during the turn, the reminder will remain at the end until the turn is over and the agent has responded.

## Tool Calls

Tool-call arguments and full results stay in chronological history across user turns. This preserves evidence for follow-up
questions and avoids rewriting a cached prefix. The original results remain available until the runtime compacts or truncates
history to meet the context budget. Legacy records use a placeholder only when no saved result is available.
> Note: in the Internal Search flow with query expansion, the Tool Call which was actually run differs from what the LLM provided as arguments.
> The tool-call arguments keep only the queries the LLM provided, and so does the model's history. The expanded queries are saved in the tool result (`SearchDocsResponse.queries`) and reach the client in `SearchToolQueriesDelta` packets, also on replay.

## Request-only context

Additional context supplied with a request goes after the stable history as an uncacheable reminder. It is available during
that run, including restoration, but does not become a historical user message. Changing this context does not rewrite the
cacheable history. File notices and step-specific reminders follow the same separation.

## Examples

```
S -> System Message
CA -> Custom Agent as a User Message
A -> Agent Message response to user
U -> User Message
TC -> Agent Message for a tool call
TR -> Tool response
R -> Reminder
F -> Point in time File
P -> Project Files (not overflowed case)
1,2,3 etc. to represent turn number. A turn consists of a user input and a final response from the Agent

Flow with Custom Agent
S, CA, U1, TC, TR, A1 -- user sends another message -> S, CA, U1, TC, TR, A1, U2, TC, TR, R
- Custom instructions stay in the preamble
- Prior tool results retain their content
- Reminder follows the current history and stays outside the cacheable prefix

Flow with Project and File Upload
S, CA, P, F, U1, A1 -- user sends another message -> S, CA, P, F, U1, A1, U2
- Project text and images stay in the preamble
- User-uploaded files stay beside their original question
- New questions extend chronological history

Reminders during a single Turn
S, CA, P, U1, TC, TR, R -- agent calls another tool -> S, CA, P, U1, TC, TR, TC, TR, R
- Only the trailing reminder changes position
- Compaction is an explicit history rewrite when the context budget requires it
```

## Product considerations

Project files remain available for the session. User attachments stay beside the question that supplied them and can leave
working history through compaction. A forgotten-files notice identifies retrieval options when the file-reader configuration
supports them.

Keeping results costs cache-read tokens and context space. Removing them saves those tokens but can force a cache write for
later messages and a new search for lost evidence. The runtime therefore manages growth through compaction rather than
removing every previous tool result at the next user turn. Cache expiry, configuration changes, and image-cap enforcement can
still cause cache misses.

Focused trailing reminders keep citation and task guidance close to generation. They do not move large instruction or file
blocks through the history.
## Reasons / Experiments

The earlier design kept custom instructions separate from the system prompt because combining them reduced instruction
following in prior experiments. It also moved those instructions and project files near each new question to improve attention.

The fixed preamble deliberately revises that placement decision: moving existing blocks breaks exact-prefix caching on each
user turn. Instructions retain their separate user-message role, and focused reminders remain near generation. Cross-turn
prefix tests verify stability, but model evaluations must also check instruction following and project-file recall in long chats.
Do not infer answer quality from cache-hit rates alone.
Different LLMs vary in this but some now have a section that cannot be set via the API layer called the "System Prompt" (OpenAI terminology) which contains
information like the model cutoff date, identity, and some other basic non-changing information. The System prompt described above is in that convention called
the "Developer Prompt". It seems the distribution of the System Prompt, by which I mean the style of wording and terms used can also affect the behavior. This
is different between different models and not necessarily scientific so the system prompt is built from an exploration across different models. It currently
starts with: "You are a highly capable, thoughtful, and precise assistant. Your goal is to deeply understand the user's intent..."

LLMs are able to handle changes in topic best at message boundaries. There are special tokens under the hood for this. We also use this property to slice up
the history in the way presented above.

Reminder messages are placed at the end of the prompt because all model fine tuning approaches cause the LLMs to attend very strongly to the tokens at the very
back of the context closest to generation. This is the only way to get the LLMs to not miss critical information and for the product to be reliable. Specifically
the built-in reminders are around citations and what tools it should call in certain situations.

The document json includes a field for the LLM to cite (it's a single number) to make citations reliable and avoid weird artifacts. It's called "document" so
that the LLM does not create weird artifacts in reasoning like "I should reference citation_id: 5 for...". It is also strategically placed so that it is easy to
reference. It is followed by a couple short sections like the metadata and title before the long content section. It seems LLMs are still better at local
attention despite having global access.

In a similar concept, LLM instructions in the system prompt are structured specifically so that there are coherent sections for the LLM to attend to. This is
fairly surprising actually but if there is a line of instructions effectively saying "If you try to use some tools and find that you need more information or
need to call additional tools, you are encouraged to do this", having this in the Tool section of the System prompt makes all the LLMs follow it well but if it's
even just a paragraph away like near the beginning of the prompt, it is often ignored. The difference is as drastic as a 30% follow rate to a 90% follow
rate by even just moving the same statement a few sentences.

## Other related pointers

- How messages, files, images are stored can be found in backend/onyx/db/models.py, there is also a README.md under that directory that may be helpful.

---

# Overview of LLM flow architecture

**Concepts:**
Turn: User sends a message and AI does some set of things and responds
Step/Cycle: 1 single LLM inference given some context and some tools

## 1. Top Level (process_message function):

This function can be thought of as the set-up and validation layer. It ensures that the database is in a valid state, reads the
messages in the session and sets up all the necessary items to run the chat loop and state containers. The major things it does
are:

- Validates the request
- Builds the chat history for the session
- Fetches any additional context such as files and images
- Captures tool configuration for each response worker
- Reserves assistant response IDs

### Launch (`start_chat_turn`)

`process_message.py` prepares chat data, launches the turn, and reads its stream.
`prepare_chat_turn` and its request preparation helpers live beside the streaming entrypoints.
Launch publishes processing status, creates delivery, queues response IDs, and starts the control thread.
Initial IDs and response packets use the same live and replay delivery path.
The recording context is copied into workers and restored on the caller before launch returns.

### Execution (`ChatTurnExecution`)

Each model response runs on an independent thread. One control thread per turn checks Stop requests and refreshes processing status.
It also renews ownership for every root and child run. These cache operations run directly on the control thread.
Storage jobs also use independent threads, so a slow save cannot block Stop checks.
Thread startup copies tenant and tracing context. There is no process-wide response admission limit or fixed worker pool.

The shared agent SDK executes each response. `ResponsePresenter` translates accepted run events into chat packets.
Each response worker constructs its tools and feature agent through `create_chat_agent` in `execution.py`.
Each `Emitter` adds response identity and model routing. `ChatDelivery` sends packets to the current reader and resumable stream buffer.
A failed model reports its own error while other comparison responses continue.

### Saved responses and delivery

The run owns accepted messages, tool results, and its terminal snapshot.
After execution ends, chat projects that snapshot into a response and starts persistence.
Save failures and saves that exceed their wait bound produce distinct persistence outcomes.
Late save completion remains tracked after delivery ends.

Closing a browser reader does not cancel execution. The non-daemon control thread stays alive until execution, storage, and delivery finish.
API shutdown waits for active chat work before closing database and tracing services. It does not cancel responses.
A process-wide work counter tracks completion without retaining turns or tenant data.
Kubernetes can force termination when the pod's shutdown grace period expires.

### Stopping generation

The control thread polls every 250 milliseconds between control passes. Slow cache calls delay the next pass.
Stop cancels each active response, saves accepted partial content, and emits `OverallStop(stop_reason="user_cancelled")`.
Run completion and resource cleanup are separate: the control thread waits while provider, tool, or save work drains.

For the execution loop, tool calls, and cancellation contracts, see the [agent SDK](../agents/README.md).

## Things to know

- Chat packets carry content, execution identity, and model routing. The frontend derives timeline positions.
  See the [chat stream contract](../agents/README.md#chat-stream) for item and update types.

- Message types serve different boundaries:
  - **ChatMessage** stores a user message, summary, or response anchor in the session tree.
    **ChatResponseItem** stores an assistant message or references a tool result within that response. Both live in [database models](../db/models.py).
  - **Message** is the SDK conversation type, defined in [LLM models](../llm/models.py).
    Storage retains these shared types; history loading filters unfinished tool calls before agent execution.
  - **ChatCompletionMessage** is the LiteLLM request message type in [provider models](../llm/model_request.py).
    The LLM adapter converts SDK messages into this provider format.


## Execution and caller deadlines

The internal constant `CHAT_RESPONSE_WAIT_TIMEOUT_S` limits a full-response caller's
wait after delivery ends to 3,600 seconds. Expiry returns a caller error; it does
not cancel execution.

The internal constant `CHAT_EXECUTION_TIMEOUT_S` sets the execution deadline to
3,600 seconds. Reaching it requests cancellation. The turn retains session ownership
until model calls, tools, storage, and delivery drain. A disconnected browser
only detaches its reader.

`MAX_LLM_CYCLES` (default 6) caps the steps of a chat response. The last step offers
no tools, so the model must answer. When code mode applies (`CODE_MODE_ENABLED` and at
least one tool runs inside programs), the cap is `CODE_MODE_MAX_LLM_CYCLES`: a safety
cap of 100, or `MAX_LLM_CYCLES` when that is higher.

## Deploying the shared runtime

Deploy the session status endpoint before clients require it. A failed readiness
check leaves input unconfirmed; clients cannot assume the session is idle.

Before enabling the new runtime, stop new submissions to old generation owners
and let their active work finish. Include API servers, Slack, and other in-process
callers. Closing browser connections does not drain their work. Old processing
fences and new ownership leases cannot safely coordinate overlapping writers.

Stream reconnection replays cached packets. It does not restart computation.
Only a valid suspended checkpoint, resumed through a runtime caller, restores
computation. A cleaned-up coding sandbox cannot generally be restored.
