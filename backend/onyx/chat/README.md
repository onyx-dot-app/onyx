# Overview of Context Management

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
Documents from search or uploaded Project files are represented as a json so that the LLM can easily understand it. It is represented with a prefix to make the
context clearer to the LLM. Note that for search results (whether web or internal, it will just be the json) and it will be a Tool Call type of message
rather than a user message.
```
Here are some documents provided for context, they may not all be relevant:
{
    documents: [
        {"citation_id": 1, "title": "Hello", "contents": "Foo", "metadata": "status closed"}
        {"citation_id": 2, "title": "World", "contents": "Bar"}
    ]
}
```
Documents are represented with citation_id so that the LLM can easily cite them with a single number. The tool returns have to be richer to be able to
translate this into links and other UI elements. What the LLM sees is far simpler to reduce noise/hallucinations.

Note that documents included in a single turn should be collapsed into a single user message.

Search tools give URLs to the LLM though so that open_url (a separate tool) can be called on them.


## Reminders
To ensure the LLM follows certain specific instructions, instructions are added at the very end of the chat context as a user message. If a search related
tool is used, a citation reminder is always added. Otherwise, by default there is no reminder. If the user configures reminders, those are added to the
final message. If a search related tool just ran and the user has reminders, both appear in a single message.

If a search related tool is called at any point during the turn, the reminder will remain at the end until the turn is over and the agent as responded.


## Tool Calls
As tool call responses can get very long (like an internal search can be many thousands of tokens), tool responses are today replaced with a hardcoded
string saying it is no longer available. Tool Call details like the search query and other arguments are kept in the history as this is information
rich and generally very few tokens.

**Possible Future Extension**:
Instead of dropping the Tool Call response, we might summarize it using an LLM so that it is just 1-2 sentences and captures the main points. That said,
this is questionable value add because anything relevant and useful should be already captured in the Agent response.


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
- Custom Agent prompt comes before project files which comes before user uploaded files in each turn

Reminders during a single Turn
S, U1, TC, TR, R -- agent calls another tool -> S, U1, TC, TR, TC, TR, R, A1
- Reminder moved to the end
```

## Reasons / Experiments
Custom Agent instructions being placed in the system prompt is poorly followed. It also degrade performance of the system especially when the instructions
are orthogonal (or even possibly contradictory) to the system prompt. For weaker models, it causes strange artifacts in tool calls and final responses
that completely ruins the user experience. Empirically, this way works better across a range of models especially when the history gets longer.
Having the Custom Agent instructions not move means it fades more as the chat gets long which is also not ok from a UX perspective.

Project files are important to the entire duration of the chat session. If the user has uploaded project files, they are likely very intent on working with
those files. The LLM is much better at referencing documents close to the end of the context window so keeping it there for ease of access.

Reminder are absolutely necessary to ensure 1-2 specific instructions get followed with a very high probability. It is less detailed than the system prompt
and should be very targetted for it to work reliably.

User uploaded files are considered relevant for that point in time, it is ok if the Agent forgets about it as the chat gets long. If every uploaded file is
constantly moved towards the end of the chat, it would degrade quality as these stack up. Even with a single file, there is some cost of making the previous
User Message further away. This tradeoff is accepted for Projects because of the intent of the feature.


## Other related pointers
- How messages, files, images are stored can be found in db/models.py
