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

## Execution

`execute_flow` walks the reachable subgraph in topological order (Kahn's
algorithm, seeded in declaration order so independent branches run the same way
every time).

Three behaviours matter when a run goes wrong:

**A node is recorded before it runs.** The unique key on
`(run_id, node_id, item_index)` is what makes a redelivered message safe: the
second attempt finds a finished row and reuses its output instead of posting the
same message to Slack twice.

**Branches skip, they do not fail.** A node whose predecessors all took the other
branch is `SKIPPED`. The canvas greys it out, and nobody has to work out whether
grey means broken.

**Expression errors are not retried.** A missing key will still be missing in two
seconds. Only `http_error`, `timeout`, `llm_error` and `node_exception` get
another attempt.

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
rather than running two copies over the same data.

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
| POST | `/flows/webhooks/{trigger_id}` |

## Adding a node kind

1. Add the member to `FlowNodeKind` in `onyx/db/enums.py`.
2. Add the spec model in `onyx/flows/models.py` and put it in the `FlowNode`
   union.
3. Write the handler in `onyx/flows/nodes/`, taking
   `(node, context, runtime)` and returning a `NodeOutcome`.
4. Register it in `NODE_EXECUTORS`.
5. Extend the `flownodekind` enum in a migration.

Handlers are plain functions so a test can call one with a hand-built context.
That is most of why the engine stays easy to reason about.
