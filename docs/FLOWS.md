# Flows

A **flow** is an automation: a trigger, plus a graph of nodes that run when it
fires. Flows are authored per user, versioned on publish, and executed
headlessly by a Celery worker.

This document covers the spec format and the execution model. It is the
reference for anyone adding a node type or debugging a run.

## The spec

A flow's spec is JSON. It lives on `flow.draft_spec` while it is being edited
and is copied into an immutable `flow_version` row on publish. A run pins the
version it started on, so editing a flow never changes a graph that is already
executing.

```yaml
spec_version: 1
start: fetch_issues
nodes:
  - id: fetch_issues
    kind: HTTP
    url: https://api.example.com/issues?state=open
    headers:
      Authorization: Bearer {{ trigger.token }}
    result_path: data.issues
    next: [has_any]

  - id: has_any
    kind: CONDITION
    left: "{{ steps.fetch_issues }}"
    operator: is_not_empty
    on_true: [summarize]

  - id: summarize
    kind: AI
    for_each: "{{ steps.fetch_issues }}"
    prompt: Summarize this issue in one line: {{ item.title }}
    output_fields:
      - { name: summary, type: text }
      - { name: severity, type: number }
```

### Validation

Parsing a spec guarantees four things:

- node ids are unique and match `^[a-z][a-z0-9_]{0,63}$`
- every `next` / `on_true` / `on_false` reference resolves
- the graph has no cycles
- `start` exists

Nodes nothing reaches are **allowed**. The editor creates one every time
someone drops a node on the canvas, and failing autosave over it would be
obnoxious. The engine simply never runs them.

## Expressions

One syntax: `{{ path }}`. Paths walk data the run already produced. There is no
evaluation and no function calls — a spec is authored in a browser and executed
on a worker, so anything richer would be remote code execution with extra steps.

| Root | Holds |
|---|---|
| `trigger` | whatever started the run (a webhook body, a manual payload) |
| `steps` | completed node outputs, keyed by node id |
| `item` | the current element while a node fans out |
| `index` | that element's 0-based position |

Paths support `.key`, `[0]`, `[-1]` and `['key-with-dashes']`.

**A lone expression keeps its type. Mixed with text, you get a string.**

```
"{{ steps.fetch.items }}"        -> the list itself
"found {{ steps.fetch.total }}"  -> "found 12"
```

That is what lets `for_each` receive a real list and a condition compare real
numbers, while a URL or a prompt still interpolates the way you would expect.

## Node kinds

### HTTP

Calls an endpoint. Output is `{status, headers, body}`, or just the slice named
by `result_path`. `fail_on_error_status` is on by default; turn it off to branch
on `status` instead.

Every request passes through an SSRF-validating transport, so redirect hops are
checked too. The policy is the tenant's `SSRF Protection` admin setting — flow
URLs are user-authored and run unattended, so they are treated like the other
LLM-initiated paths rather than like an admin-configured connector.

Response headers are filtered to a known-safe set before they reach the run
history; `set-cookie` in particular never gets persisted.

### TRANSFORM

Builds an object from expressions, one per field. Fields are independent — one
cannot read another's result — so the node is order-free.

This is why there is no `Set` node: reshaping is a property of a node, not a box
on the canvas.

### CONDITION

Compares two values and hands control to `on_true` or `on_false`. Operators:
`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `not_contains`, `is_empty`,
`is_not_empty`.

Comparison is deliberately loose across the JSON/text boundary: a webhook
delivers `"200"` where an HTTP node produces `200`, and nobody editing a flow
wants to think about which side is which.

The output records both operands next to the verdict, which costs a few bytes
and saves the "but why did it go left?" conversation every time.

### AI

Sends a prompt and returns the fields you declared, at the types you declared.

Declaring fields rather than a JSON schema keeps the editor simple and gives
downstream nodes something concrete to reference. Values are coerced, not merely
checked — models answer `"0.8"` where a number was asked for, and failing an
overnight run over a pair of quotes helps nobody. A reply that cannot be
reconciled is retried once with the problem quoted back, then fails the node
with `output_mismatch`.

With no `output_fields`, the node returns `{"text": ...}`.

### HUMAN

Stops and waits for a person, then continues down `on_approve` or `on_reject`.
See [Approvals](#approvals) for what happens to the run in between.

An empty `on_reject` is the plain approval gate: rejecting stops the run and
marks it `FAILED` with `decision_rejected`. A rejected deploy reading as a clean
success is exactly the kind of thing nobody notices until it matters. Wire a
reject branch when a "no" should do something instead.

`assignee` says who ought to answer. It is informational — the flow's owner can
always decide, because an access rule here means a run stuck forever behind
somebody who left.

### CODE

Runs a snippet of Python in the code interpreter sandbox.

Never in the worker. Worker processes hold database credentials, connector
secrets and the tenant's whole environment, and a flow is authored in a browser
by anyone who can edit it.

The snippet sees `trigger`, `steps`, `item` and `index` as plain data, and
whatever it assigns to `result` becomes the node's output. Output is
`{result, logs}`, where `logs` is whatever the snippet printed — usually how you
find out what it actually saw.

```python
rows = steps["fetch"]["body"]["items"]
overdue = [row for row in rows if row["days"] > 30]
print(f"{len(overdue)} of {len(rows)} are overdue")
result = {"overdue": overdue}
```

Two details of the handover, for when you have to debug it:

- **Context arrives on stdin**, not interpolated into the source. Baking a run's
  data into a program means escaping it correctly every time forever, and one
  stray quote in an API response would be a syntax error at best.
- **The snippet is compiled under its own filename**, so a traceback carries the
  author's line numbers rather than the wrapper's.

Needs `CODE_INTERPRETER_BASE_URL`. Without it the node fails with `code_error`
saying so, and the rest of the flow package stays usable.

### LOOP

Cuts a list into batches. Output is `{batches, batch_count, total}`.

A spec is acyclic, so there is no jumping backwards; looping here means handing
the next node a manageable slice instead of four hundred items at once. Pair it
with `for_each` on the node that follows:

```
loop.over       = "{{ steps.fetch.body.rows }}"
loop.batch_size = 25
send.for_each   = "{{ steps.loop.batches }}"
```

`send` then runs once per batch with `{{ item }}` bound to the 25 rows, which is
the shape most bulk APIs actually want.

### RETRY

Calls an endpoint over and over until the answer is the one you are waiting
for. Output is `{result, checks, satisfied}`, where `result` is the last
response in the same `{status, headers, body}` shape an HTTP node produces.

Not the same thing as `retry` on a node, and the difference is the whole
reason it exists:

| | fires when |
|---|---|
| `retry` policy | the step **raised** — a timeout, a refused connection, a 500 |
| RETRY node | the step **succeeded and said "not yet"** |

That is the long-job-behind-an-API shape: you POST some work, you get a job id,
and then you sit there asking whether it is done. Without this you would need a
cycle in the graph, and a spec is acyclic on purpose.

The two layers compose rather than overlap. A transient error still propagates
out of the loop and is handled by the node's own retry policy; only an
unsatisfied condition is handled inside it.

```
poll.url              = "https://api.example.com/exports/{{ steps.start.body.id }}"
poll.until_path       = "state"
poll.operator         = "eq"
poll.value            = "complete"
poll.max_checks       = 30
poll.interval_seconds = 10
```

A path that is not there yet counts as "not yet" rather than as an error — an
endpoint that omits `state` until the job starts is answering the question.
Running out of checks fails the node with `retry_exhausted`; turn
`fail_when_exhausted` off to carry on and branch on `satisfied` instead.

The node sleeps inside one step rather than across the graph, so the spec caps
`max_checks × interval_seconds` at 600 s. Without that, one step could eat the
whole run budget on its own.

### WEBHOOK

POSTs a payload to an outside system. Output is
`{delivered, signed, status, headers, response}`.

The HTTP node can already send a POST. What it cannot do is prove the delivery
came from here, and that is the difference: a webhook node signs the body it
sends, so a receiver can tell a real delivery from anything else that found the
URL.

Two headers ride along:

```
X-Onyx-Timestamp: 1780531200
X-Onyx-Signature: <hex>
```

The signature is `HMAC-SHA256(secret, f"{timestamp}.{raw_body}")`. Signing the
timestamp too is what stops a captured delivery being replayed later — a
receiver rejects anything older than its own tolerance. To verify:

```python
signed = f"{headers['X-Onyx-Timestamp']}.{raw_body}"
expected = hmac.new(secret, signed.encode(), hashlib.sha256).hexdigest()
hmac.compare_digest(expected, headers["X-Onyx-Signature"])
```

The secret is per **flow**, not per node — a receiver verifies deliveries from
a flow. It is minted when the flow is created (or on first read, for flows that
pre-date webhook nodes), kept in `flow.webhook_signing_secret` as an
`EncryptedString`, and served to the flow's owner on `GET /flows/{flow_id}`.
Unlike an inbound trigger's secret it is readable more than once, because
setting up another receiver means copying it again.

A webhook does **not** fail the run on a 4xx or 5xx by default. A receiver
being down is their outage, not a reason to stop an automation that has already
done its work; `fail_on_error_status` turns that around.

### DELAY

Waits, then carries on. Output is `{waited_seconds, parked}`.

How it waits depends on how long for:

| `seconds` | what happens |
|---|---|
| ≤ 60 | sleeps where it stands |
| > 60 | parks the run — see [Delays](#delays) |

The threshold is fixed rather than configurable because the trade is fixed:
parking costs one sweep tick, so below a minute the park would be slower than
the wait it replaces. The ceiling is 30 days.

### FILTER

Keeps the elements of a list that match a comparison. Output is
`{items, kept, dropped, total}`.

A condition picks a branch for the whole run; a filter picks elements. Pair it
with `for_each` on whatever comes next and you have "do this to the ones that
matter", which is most of what a flow over a list is for.

```
keep.over     = "{{ steps.fetch.body.rows }}"
keep.left     = "{{ item.state }}"
keep.operator = "eq"
keep.right    = "open"
send.for_each = "{{ steps.keep.items }}"
```

`left` is evaluated once per element with `{{ item }}` and `{{ index }}`
bound, so a filter can compare an element against something an earlier step
produced rather than only against a constant.

`dropped` comes back alongside the survivors because "it did nothing" and
"everything was filtered out" look identical downstream otherwise, and those
are very different bugs.

### SCHEDULE

Waits until the next time a cron expression comes round. Output is
`{waited_seconds, parked}`, the same shape a delay produces.

The sibling of [DELAY](#delay): that one waits for a duration, this one waits
for a moment. "Finish the work now, send the digest at nine tomorrow" is the
shape, and a duration cannot express it without the author redoing the
arithmetic every time.

It parks on exactly the same machinery, at the same 60 s threshold — a next
occurrence inside a minute sleeps instead — so the two kinds behave alike.
Cron is read in **UTC**, matching the schedule triggers, so there is one
answer to "what does 9 mean" across the product.

An unusable expression is refused when the flow is saved, not when it runs,
so a typo comes back while the author is still looking at the field.

### MERGE

Brings the output of several earlier steps back together. Output is
`{values, present, missing}`, or `{items, total, present, missing}` in
`append` mode.

A graph could already fan out and join — a node runs as soon as any
predecessor hands control to it. What it could not do is see what the *other*
branch produced, and that is what this is for: two calls in parallel, one step
that uses both.

```
left.next     = ["both"]
right.next    = ["both"]
both.sources  = ["left", "right"]
both.mode     = "combine"       # -> {{ steps.both.values.left.body }}
```

`sources` is **not** adjacency — those steps already name this one in their
`next`. It is a choice among what has run, so a node with three inputs can
merge two of them. Each source must be an ancestor of the merge, which is
checked when the spec is parsed: a source that does not lead here has either
not run yet or never will, and naming sources while forgetting to wire them is
the easy slip.

A source that did not run contributes nothing rather than failing, which is
the normal case after a condition — one branch ran, the other was skipped.
`present` and `missing` say which, because that is the whole question a merge
below a branch exists to answer, and reading it off the shape of the values
would mean guessing. A source that ran and returned `null` counts as present:
"the branch was skipped" and "the step returned nothing" are different
answers.

`append` joins the sources' lists into one, wrapping a source that produced a
single value rather than rejecting it, and is capped at the fan-out limit.

## Execution

`execute_flow` walks the reachable subgraph in topological order (Kahn's
algorithm, seeded in declaration order so independent branches run the same way
every time).

Four behaviours matter when a run goes wrong:

**A node is recorded before it runs.** The unique key on
`(run_id, node_id, item_index)` is what makes a redelivered message safe: the
second attempt finds a finished row and reuses its output instead of posting the
same message to Slack twice.

**Branches skip, they do not fail.** A node whose predecessors all took the other
branch is `SKIPPED`. The canvas greys it out, and nobody has to work out whether
grey means broken.

**Expression errors are not retried.** A missing key will still be missing in two
seconds. Only `http_error`, `timeout`, `llm_error` and `node_exception` get
another attempt. A RETRY node's own loop is separate from this: see
[RETRY](#retry).

**A run waiting on a person holds nothing.** See below.

### Approvals

A HUMAN node parks the run: its status becomes `AWAITING_DECISION`, the node
keeps an open row, and `execute_flow` returns. Nothing is held in memory, so a
parked run survives a deploy, a worker crash and a week of nobody looking at it.

Answering writes the decision onto that node's row, puts the run back to
`QUEUED` and enqueues it again. The engine then walks the graph **from the top**
and reuses every row it already wrote — the same resume machinery a redelivered
Celery message uses, which is why there is no separate "continue from here" path
to get wrong.

Two consequences worth knowing:

- A node that picks a branch has to say which way it went when replayed, not
  just what it produced. That is `NODE_REPLAYERS`; without it a resumed run
  would fall back to the node's empty `next` list and skip everything below the
  branch it actually took.
- Skipping is written idempotently, because the replay reaches the same untaken
  branches a second time and the unique key on `(run_id, node_id, item_index)`
  does not care that it is the same answer.

`AWAITING_DECISION` is not terminal, and a parked run counts as in flight — a
schedule queues behind it rather than putting a second question in front of the
same person.

### Delays

A DELAY or SCHEDULE node waiting more than 60 s parks the run the same way,
with one difference: nobody has to do anything. The status becomes `AWAITING_DELAY` and the due time
goes on `flow_run.resume_at`, behind a partial index that only covers parked
runs.

`resume_delayed_flow_runs` (primary, every 30 s) claims due runs with
`FOR UPDATE SKIP LOCKED`, closes the open waiting row, puts the run back to
`QUEUED` and enqueues it — the exact counterpart of the decision endpoint.
Closing that row is what matters: without it the replay would walk into the
same wait and park again.

Both [DELAY](#delay) and [SCHEDULE](#schedule) park this way, so the sweep
looks for an open row of either kind. A due run with no open waiting row is
failed rather than re-queued, because re-queueing it would loop.

So a delay costs no worker while it waits, and "follow up tomorrow" survives a
deploy in the middle of it. A run that comes back finds no `resume_at` on its
row, because `mark_run_status` always assigns it — a finished run must not
advertise a wait that is no longer coming.

### Fan-out

A node with `for_each` runs once per element, with `{{ item }}` and
`{{ index }}` bound, and records the per-item outputs as its own output. Capped
at 200 items.

Fan-out is explicit in the spec even though the editor fills it in
automatically, so the convenience lives in the UI and the engine stays
predictable.

### Budgets

A run gets 15 minutes of wall clock, checked before each node and before each
retry sleep. This is enforced in the engine because Celery's thread-pool worker
silently ignores `soft_time_limit`.

## Triggers

| Kind | Fires when |
|---|---|
| `SCHEDULE` | a cron expression comes due |
| `WEBHOOK` | an external system POSTs to the trigger's URL |
| `MANUAL` | someone presses Run |

`dispatch_due_flows` runs every 30 s on the primary queue, claims due schedule
triggers with `FOR UPDATE SKIP LOCKED`, advances `next_run_at`, and enqueues the
executor. A flow whose previous run is still going records a `SKIPPED` run
rather than running two copies over the same data — and a run parked on an
approval or a delay counts as still going.

Webhooks authenticate with a secret returned once, when the trigger is created.
Every rejection answers 404, so the endpoint cannot be probed for which triggers
exist.

```
POST /flows/webhooks/{trigger_id}
X-Onyx-Flow-Token: <secret>
```

## Lifecycle

```
draft  --publish-->  version N  --activate-->  scheduled runs
  |                                              |
  +--- test run (executes the draft) ------------+
```

- New flows start `PAUSED`. Saving should never be the same gesture as putting
  something into production.
- Activating requires a published version.
- Test runs execute the draft and stay out of the default run history, so trying
  something out does not litter the record an owner reads to check the
  automation is healthy.

## Retention

`purge_old_flow_runs` runs daily. A run is dropped only when it is both older
than 30 days **and** outside the newest 100 for its flow, so a busy flow keeps
its recent history and a quiet one does not hoard a year of green ticks.

## API

| Method | Path |
|---|---|
| POST | `/flows` |
| GET | `/flows` |
| GET | `/flows/{flow_id}` |
| PATCH | `/flows/{flow_id}` |
| DELETE | `/flows/{flow_id}` |
| POST | `/flows/{flow_id}/publish` |
| POST | `/flows/{flow_id}/status` |
| PUT | `/flows/{flow_id}/triggers` |
| POST | `/flows/{flow_id}/run?test=true` |
| GET | `/flows/{flow_id}/runs` |
| GET | `/flows/{flow_id}/runs/{run_id}` |
| POST | `/flows/{flow_id}/runs/{run_id}/decision` |
| POST | `/flows/webhooks/{trigger_id}` |

## Adding a node kind

1. Add the member to `FlowNodeKind` in `onyx/db/enums.py`.
2. Add the spec model in `onyx/flows/models.py` and put it in the `FlowNode`
   union.
3. Write the handler in `onyx/flows/nodes/`, taking
   `(node, context, runtime)` and returning a `NodeOutcome`.
4. Register it in `NODE_EXECUTORS`.
5. If the kind picks a branch, write a replayer too and register it in
   `NODE_REPLAYERS`. See [Approvals](#approvals) for why.
6. Check the name fits `flow_node_run.kind`. The column is a plain `VARCHAR`
   sized to the longest member, so a longer name needs a widening migration.

Handlers are plain functions so a test can call one with a hand-built context.
That is most of why the engine stays easy to reason about.
