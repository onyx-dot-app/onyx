# Overview of Context Management

This document reviews some design decisions around the main agent-loop powering Onyx's chat flow.
It is highly recommended for all engineers contributing to this flow to be familiar with the concepts here.

> Note: it is assumed the reader is familiar with the Onyx product and features such as Projects, User files, Citations, etc. 

## System Prompt

The system prompt is a default prompt that comes packaged with the system. Users can edit the default prompt and it will be persisted in the database.

Some parts of the system prompt are dynamically updated / inserted:

- Datetime of the message sent
- Tools description of when to use certain tools depending on if the tool is available in that cycle
- If the user has just called a search related tool, then a section about citations is included

## Custom Agent Prompt

The custom agent is inserted as a user message above the most recent user message, it is dynamically moved in the history as the user sends more messages.
If the user has opted to completely replace the System Prompt, then this Custom Agent prompt replaces the system prompt and does not move along the history.

## How Files are handled

On upload, Files are processed for tokens, if too many tokens to fit in the context, it’s considered a failed inclusion. This is done using the LLM tokenizer.

- In many cases, there is not a known tokenizer for each LLM so there is a default tokenizer used as a catchall.
- File upload happens in 2 parts - the actual upload + token counting.
- Files are added into chat context as a “point in time” inclusion and move up the context window as the conversation progresses.
  Every file knows how many tokens it is (model agnostic), image files have some assumed number of tokens.

Image files are attached to User Messages also as point in time inclusions.

**Future Extension**:
Files selected from the search results are also counted as “point in time” inclusions. Files that are too large cannot be selected.
For these files, the "entire file" does not exist for most connectors, it's pieced back together from the search engine.

## Projects

If a Project contains few enough files that it all fits in the model context, we keep it close enough in the history to ensure it is easy for the LLM to
access. Note that the project documents are assumed to be quite useful and that they should 1. never be dropped from context, 2. is not just a needle in
a haystack type search with a strong keyword to make the LLM attend to it.

Project files are vectorized and stored in the Search Engine so that if the user chooses a model with less context than the number of tokens in the project,
the system can RAG over the project files.

## How documents are represented

Documents from search or uploaded Project files are represented as a json so that the LLM can easily understand it. It is represented with a prefix string to
make the context clearer to the LLM. Note that for search results (whether web or internal, it will just be the json) and it will be a Tool Call type of
message rather than a user message.

```
Here are some documents provided for context, they may not all be relevant:
{
    "documents": [
        {"document": 1, "title": "Hello", "metadata": "status closed", "contents": "Foo"},
        {"document": 2, "title": "World", "contents": "Bar"}
    ]
}
```

Documents are represented with the `document` key so that the LLM can easily cite them with a single number. The tool returns have to be richer to be able to
translate this into links and other UI elements. What the LLM sees is far simpler to reduce noise/hallucinations.

Note that documents included in a single turn should be collapsed into a single user message.

Search tools also give URLs to the LLM so that open_url (a separate tool) can be called on them.

## Reminders

To ensure the LLM follows certain specific instructions, instructions are added at the very end of the chat context as a user message. If a search related
tool is used, a citation reminder is always added. Otherwise, by default there is no reminder. If the user configures reminders, those are added to the
final message. If a search related tool just ran and the user has reminders, both appear in a single message.

If a search related tool is called at any point during the turn, the reminder will remain at the end until the turn is over and the agent has responded.

## Tool calls

Native history retains the model's tool arguments and each tool result.
When the input budget becomes tight, `ClearToolResults` replaces older result content with a short marker.
`SlidingWindowCompaction` can then remove older conversation history while preserving valid tool pairs.
Search query expansion remains tool behavior; it does not rewrite native model messages.

Persisted branch summaries use native `SummarizingCompaction`.
See [Chat history compaction](COMPRESSION.md) for the persistence boundary.

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
S, U1, TC, TR, A1, CA, U2, A2  -- user sends another message, triggers tool call -> S, U1, TC, TR, A1, U2, A2, CA, U3, TC, TR, R, A3
- Custom agent response moves
- Reminder inserted after TR

Flow with Project and File Upload
S, CA, P, F, U1, A1 -- user sends another message -> S, F, U1, A1, CA, P, U2, A2
- File stays in place, above the user message
- Project files move along the chain as new messages are sent
- Custom Agent prompt comes before project files which come before user uploaded files in each turn

Reminders during a single Turn
S, U1, TC, TR, R -- agent calls another tool -> S, U1, TC, TR, TC, TR, R, A1
- Reminder moved to the end
```

## Product considerations

Project files are important to the entire duration of the chat session. If the user has uploaded project files, they are likely very intent on working with
those files. The LLM is much better at referencing documents close to the end of the context window so keeping it there for ease of access.

User uploaded files are considered relevant for that point in time, it is ok if the Agent forgets about it as the chat gets long. If every uploaded file is
constantly moved towards the end of the chat, it would degrade quality as these stack up. Even with a single file, there is some cost of making the previous
User Message further away. This tradeoff is accepted for Projects because of the intent of the feature.

Reminder are absolutely necessary to ensure 1-2 specific instructions get followed with a very high probability. It is less detailed than the system prompt
and should be very targetted for it to work reliably and also not interfere with the last user message.

## Reasons / Experiments

Custom Agent instructions being placed in the system prompt is poorly followed. It also degrades performance of the system especially when the instructions
are orthogonal (or even possibly contradictory) to the system prompt. For weaker models, it causes strange artifacts in tool calls and final responses
that completely ruins the user experience. Empirically, this way works better across a range of models especially when the history gets longer.
Having the Custom Agent instructions not move means it fades more as the chat gets long which is also not ok from a UX perspective.

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
- Prepares all of the tools for the LLM
- Creates the state container objects for use in the loop

### Execution (`_run_models` function):

Each model runs in its own worker thread inside a `ThreadPoolExecutor`. Workers write packets to a shared
`merged_queue` via an `Emitter`; the main thread drains the queue and yields packets in arrival order. This
means the top level is isolated from the LLM flow and can yield packets as soon as they are produced. If a
worker fails, the main thread yields a `StreamingError` for that model and keeps the other models running.
All saving and database operations are handled by the main thread after the workers complete (or by the
workers themselves via self-completion if the drain loop exits early).

### Emitter

The emitter delivers stream events to the outer response flow. Each `Emitter` tags every packet with a `model_index` and places it on the shared
`merged_queue` as a `(model_idx, packet)` tuple. The drain loop in `_run_models` consumes these tuples and
yields the packets to the caller. Both the emitter and the state container are mutating state objects used
only to accumulate state. There should be no logic dependent on the states of these objects, especially in
the lower levels. The emitter also exposes the disconnect signal to the native cancellation watcher.

### State Container

The state container is used to accumulate state during the LLM flow. Similar to the emitter, it should not be used for logic,
only for accumulating state. It is used to gather all of the necessary information for saving the chat turn into the database.
So it will accumulate answer tokens, reasoning tokens, tool calls, citation info, etc. This is used at the end of the flow once
the lower level is completed whether on its own or stopped by the user. At that point, all of the state is read and stored into
the database. The state container can be added to by any of the underlying layers, this is fine.

### Stopping Generation

The drain loop in `_run_models` checks `check_is_connected()` every 50 ms (on queue timeout). The signal itself
is stored in Redis and is set by the user calling the stop endpoint. On disconnect, the drain loop saves
partial state for every model, yields an `OverallStop(stop_reason="user_cancelled")` packet, and returns.
A `drain_done` event signals emitters to stop blocking so worker threads can exit quickly. Workers that
already completed successfully will self-complete (persist their response) if the drain loop exited before
reaching the normal completion path.

## Native agent execution

`chat_agent.run_chat_agent` prepares application context and starts a Pydantic AI `Agent`.
`agent_runtime.build_native_agent` configures the shared execution path.
The synchronous entry point is used only at the application boundary.
Pydantic AI owns model requests, tool dispatch, validation retries, and termination.

Each run creates its own agent, provider clients, callbacks, and cancellation token.
The run closes its provider clients before its event loop exits.
Research and coding tools await native harness `SubAgent` delegation on the parent event loop.
Typed domain tools retain repository arguments, citations, and result persistence.
Each child has its own request budget and deadline. These budgets are independent of the coordinator request budget.
Per-request billing records both coordinator and child usage.
Credentials and conversation state never live on a shared agent.

A native request hook adds application prompts, settings, and active tools before each model request.
The harness `TieredCompaction` first clears older tool results, then trims older history.
Compaction keeps native message types, including tool pairs and provider thinking signatures.
Required prompts and the latest question must fit the selected model's input budget.
The runtime checks this limit after compaction and includes tool definitions in the estimate.

Saved chat records become native `ModelMessage` objects directly.
Images use `BinaryContent`; supported explicit caching uses native `CachePoint` markers.

Tools expose JSON schemas to Pydantic AI and return tool results.
Pydantic AI schedules parallel tools. Synchronous domain tools run in worker threads.
Tool progress uses native custom events through `RunContext.emit`.
The central stream handler delivers these domain events to the application emitter.
Tools do not construct transport packets.

Native memory uses the harness `Memory` capability.
`UserMemoryStore` persists notebook files in existing user memory rows.
Metadata adds stable file paths, version checks, and durable operation receipts.
Each store fixes its tenant and user when the run starts.
Incognito runs do not create a memory capability.

## Stream events and placement

The transport wraps Pydantic AI events with placement and phase fields.
The frontend reads native text and thinking events directly.
`part_end` contains accumulated content; renderers must not append that content again.
Domain events still carry search documents, generated files, citations, and memory changes.

Phases distinguish chat, clarification, planning, research, reports, and coding.
Placement assigns display groups and parallel branches.
A placement `turn_index` identifies a display group, not a conversation turn.
Nested tools use `sub_turn_index` within their parent's group.

Citation processing changes displayed text while preserving raw model history.
The state container stores the displayed answer and tool snapshots for replay.
A cancellation token stops the graph when the emitter observes a disconnect.
The outer message flow still saves partial responses and handles multi-model delivery.

## Message boundaries

Database `ChatMessage` rows become `ChatMessageSimple` records before execution.
`history_translation.py` converts persisted application records at the run boundary.
Pydantic AI `ModelMessage` objects remain the source of truth throughout the active run.
Generated history does not pass through legacy message objects between model requests.
