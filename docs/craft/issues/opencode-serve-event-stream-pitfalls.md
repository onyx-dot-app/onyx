# Opencode-serve event stream: turn termination & delta races

**Audience:** engineers working on the opencode-serve transport —
specifically the consumer logic that translates an upstream agent
event stream into ACP packets for the frontend. Captures three real
bugs found in the translator and the broader event-ordering principles
that surfaced from investigating them.

**Status:** all three issues fixed. This doc explains the bugs, why
the original assumptions were wrong, and the resilience patterns the
translator now applies. Future work in the optional final section.

The relevant code lives under
`backend/onyx/server/features/build/sandbox/opencode/serve_client.py`
and the unit tests under
`backend/tests/unit/onyx/server/features/build/sandbox/test_translate_opencode_event.py`.

---

## TL;DR

The upstream event stream has three properties that bit the original
translator implementation:

1. **A turn contains multiple steps.** Each step emits its own
   "message completed" signal. That signal is not a turn terminator.
2. **The session-status payload is an object, not a string.** Naive
   equality checks against a string never match, silently disabling
   one of the two intended end-of-turn signals.
3. **Content deltas race ahead of their parent message's metadata.**
   Up to ~300ms of leading deltas can arrive before the consumer has
   a way to classify them as assistant vs user output.

Each defect by itself produced a subtly different user-visible
symptom; together they produced an unpredictable mix of empty turns,
truncated turns, and stuck "still generating" UI states.

---

## 1. Premature turn termination on per-step completion

### Symptom

A turn that included a tool call followed by a model answer would
render the tool call to the user but never the answer. The frontend
would see `prompt_response: end_turn` immediately after the tool
finished, and any text the model emitted afterwards never reached the
UI.

Sometimes the agent would respond with only tool output for several
turns in a row, then produce a long "summary" answer on a later turn
that referenced everything that had happened in the dropped turns —
indicating the model *was* producing text, but it was being thrown
away mid-stream.

### Root cause

The original terminator fired whenever a `message.updated` event
arrived with `info.role == "assistant"` and `info.time.completed` set.
The assumption was that "completed" meant "the assistant is done with
this turn."

In practice, the upstream agent runs a multi-step inner loop per turn:

```
turn
├── step 0: assistant message with reasoning + a tool call
├── step 1: tool execution result
├── step 2: assistant message with another tool call
├── ...
└── step N: assistant message with the final answer text
```

Each step's assistant message is "completed" as soon as that step
ends. So `message.updated` with `time.completed` fires N times per
turn — once per step — and our terminator fired on the first one
(usually the reasoning-plus-tool-call step). Subsequent steps,
including the one with the user-visible answer, were dropped because
the consumer had already yielded `prompt_response` and returned.

### Fix

The correct turn-level signals are:

- `session.idle` event, or
- `session.status` event with the inner status discriminator set to
  `idle`.

These fire exactly once per turn, after the agent's inner loop has
exited. `message.updated` is now used only for caching role/finish
metadata and for surfacing message-level errors (which legitimately
do kill the turn). The LLM finish reason from the *last*
`message.updated` is captured into `_TurnState.last_finish` so the
eventual terminator from `session.idle` can populate the ACP
`stop_reason` correctly.

### Lesson

When integrating with any external event stream, distinguish between
**step-level** signals (one per inner loop iteration) and
**turn-level** signals (one per outer interaction). They look
similar from a single example but produce wildly different counts in
multi-step interactions. If a turn-level field doesn't exist
explicitly, find the event that fires *once* at the boundary —
typically the "ready for next input" or "idle" signal.

---

## 2. Session-status payload shape mismatch

### Symptom

`session.status` events were silently ignored, even when they should
have terminated the turn. Tests passed because they also used the
wrong shape. The bug was masked because the deprecated `session.idle`
event was still being emitted in parallel and our `session.idle`
handler was correct.

### Root cause

The handler was:

```python
if etype == "session.status":
    if props.get("status") == "idle":  # ← compares dict to string
        yield from _emit_terminator(state)
    return
```

The actual upstream shape is:

```json
{
  "type": "session.status",
  "properties": {
    "sessionID": "...",
    "status": { "type": "idle" }
  }
}
```

`status` is a tagged-union object whose discriminator is `.type`. The
union covers at least `idle`, `busy`, and `retry`, with the latter
two carrying extra fields like `attempt` and `message`.

The buggy comparison `dict == "idle"` always evaluates to `False`, so
the handler never fired.

### Fix

```python
if etype == "session.status":
    status = props.get("status")
    if isinstance(status, dict) and status.get("type") == "idle":
        yield from _emit_terminator(state, finish=state.last_finish)
    return
```

### Lesson

When an upstream API uses tagged-union payloads, always inspect the
real shape before writing equality checks. Schema files (or
TypeScript types, or OpenAPI specs) are easy to misread when the
field name (`status`) collides with what you'd expect a stringly-typed
value to look like.

This is also a tests-don't-protect-you-from-spec-drift situation:
both the production code and the test fixture used `"status":
"idle"`, so the unit tests were self-consistent and green while the
real integration was dead. Whenever possible, derive test fixtures
from a captured real payload rather than re-typing one by hand.

---

## 3. Content deltas racing ahead of message metadata

### Symptom

Some turns came back with `events=1` from the backend — meaning only
the terminator made it out and zero content events were emitted. The
SSE stream from the agent on those same turns showed assistant text
deltas being published normally. Content was being dropped between
the upstream stream and our consumer.

### Root cause

The upstream agent emits two kinds of events for assistant text:

1. **`message.part.delta`** — the streaming content chunks themselves.
2. **`message.updated`** — the message-level metadata, including the
   role (`assistant` vs `user`) and which message ID owns the parts.

The translator needed to filter content by role: only assistant text
should reach the frontend. A user message's part events (echoes,
retroactive updates) must be dropped. The natural way to write that
filter is "ignore deltas whose `messageID` we haven't seen claim
role=assistant yet."

In practice, **deltas arrive ahead of the matching `message.updated`
by 1–300ms**. The race is consistent and observable. With the naive
filter, those leading deltas were dropped — and if the entire visible
text for a step fit in that race window (often the case for short
answers like one-line bash output explanations), the whole step's
text was lost.

### Fix

Mirroring the pattern used by upstream's own reference consumer: when
a delta arrives for an unknown messageID, **synchronously REST-fetch
the message** to hydrate its role and part metadata, then process the
delta against the freshly-populated cache.

The new method `OpencodeServeClient.get_message(session_id,
message_id)` performs the lookup. The translator helper
`_hydrate_message` populates `_TurnState.assistant_message_ids`,
`_TurnState.user_message_ids`, and `_TurnState.part_types` from the
response. `_is_assistant_message` is the single chokepoint all three
content paths (delta, text part, reasoning part) go through:

```python
def _is_assistant_message(state, msg_id):
    if not isinstance(msg_id, str):
        return False
    if msg_id in state.assistant_message_ids:
        return True
    if msg_id in state.user_message_ids:
        return False
    return _hydrate_message(state, msg_id) == "assistant"
```

The hydrate is cached, so each message is fetched at most once per
turn. A user-message lookup is also cached (in `user_message_ids`) so
we don't refetch on every echoed delta of a user message.

### Why not buffer instead?

An earlier attempt buffered the unknown-msg deltas in
`_TurnState.pending_events` and replayed them when `message.updated`
finally arrived. That works for the happy path but loses content if
the connection drops or the upstream stream crashes before
`message.updated` fires. The REST hydrate is independent of the
event stream — if upstream has the message persisted, we can recover
it regardless of stream state. Latency tradeoff: ~5–50ms blocking
HTTP call on the first delta per message, which is acceptable for
in-pod traffic.

### Lesson

Don't assume an event stream's ordering is part of its contract just
because it works that way most of the time. Race windows of 1–300ms
are easy to miss in casual testing and very easy to hit in
production. If your consumer's correctness depends on event A
arriving before event B, but A and B are emitted by separate
internal paths in the producer, treat them as racing and design for
either order. The pattern that survives is "cache-first, fall back
to a synchronous fetch on miss" — exactly what the upstream's own
reference consumer does.

---

## Cross-cutting principle: stream is a hint, REST is truth

The three fixes above all point at one underlying principle: the
event stream is a **performance optimization** for the frontend,
not the **source of truth** for session state. The source of truth
is the persisted state behind the REST API.

When the stream is lossy, racy, or ambiguous, the right answer is
almost always to fall back to a REST call against the persisted
state rather than to invent compensating logic that re-derives the
state from a partial view of the stream.

Concretely, in the current translator:

- **Role classification** — REST `GET /session/{id}/message/{id}` on
  unknown messageID.
- **Reconnect recovery (future)** — same endpoint would let us
  rebuild state after a dropped SSE connection.
- **Turn-end disambiguation** — `session.status:{type:idle}` IS a
  stream signal, but if we ever doubt it, the `GET /session/{id}`
  endpoint exposes the current state directly.

---

## Optional future work

These are noted for visibility but not blockers for the current
transport rollout.

### Surface `session.status` to the frontend

The translator currently consumes `session.status` only for the
`idle` terminator path. The `busy` and `retry` cases (with their
`attempt` and `message` fields) are informationally rich — `retry`
in particular signals that the upstream is auto-retrying a flaky
LLM call. Forwarding these to the frontend as a new ACP event type
would unlock:

- A "generating…" / "retrying (attempt 2)…" / "idle" indicator next
  to each session row.
- Auto-recovery UX when retry exhausts (surface the error message
  instead of just a generic failure).
- Cross-tab status awareness if combined with a persisted
  `agent_status` column on the build session.

Three escalating implementation tiers exist (client-only,
client+server-persisted, server-push) depending on how rich the
status indicator should be.

### Reconnect-time stream replay

If the SSE connection between our backend and the upstream agent
drops mid-turn, events emitted during the gap are lost — the stream
is fire-and-forget. A robust consumer would, on reconnect, refetch
the current message-and-parts via REST and reconcile against the
local accumulator to fill any gap. The translator's
`_reconcile_text_part` helper already supports this pattern for
deltas; what's missing is the higher-level decision to issue the
REST call on reconnect.

### Replace the buffering helper with hydrate-by-default

The translator still contains a few defensive code paths from the
buffering era. They're harmless but unused. Worth a follow-up
cleanup pass.

---

## Recap: what an opencode-serve consumer needs to get right

1. Treat `session.idle` (or `session.status:{type:idle}`) as the
   only turn-level terminator. `message.updated` is per-step.
2. Inspect tagged-union payloads via their `.type` discriminator,
   not via string equality on the union itself.
3. When a content event arrives for a message you haven't classified
   yet, REST-fetch the message synchronously rather than buffering
   and hoping the metadata arrives later.
4. Capture LLM finish reason from `message.updated` as it streams
   by, and surface it on the terminator that eventually fires.
5. Cache aggressively — once per message, once per part — to keep
   hot-path latency low even when REST hydration is in play.
