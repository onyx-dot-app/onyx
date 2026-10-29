# Fleet Telemetry

> The outbound health, usage and indexing events that each Onyx deployment
> sends to the Onyx fleet service. It must never slow or fail the work it
> observes.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

- **An operator** gets fleet telemetry with no setup. Each deployment sends
  approved health, usage and indexing values to `https://telemetry.onyx.app`. It never sends document content, names,
  credentials, query or answer text, user identities or full email addresses.
  `DISABLE_TELEMETRY=true` on every service turns it off.
  `deployment/fleet-telemetry.md` is the operator reference and lists each
  event.
- **Onyx staff** see each deployment, and each cloud tenant, as a customer in
  the fleet dashboard. The dashboard lives in a separate repository.
- When the fleet service is down, the operator and the users see nothing.
  Events back off and then drop.

---

## Scope

This component holds the sender that runs in each process, the field
allowlist, the query timing wrappers, the process resource reports, the
periodic collection pass that reads the database, and the deployment key.

It does not own:
- Cloud PostHog analytics (`mt_cloud_telemetry`), which run only under
  `MULTI_TENANT`. `DISABLE_TELEMETRY` does not affect them. Their module has
  "telemetry" in its name, but it is not fleet telemetry ([[observability]]).
- Sentry, Prometheus and LLM tracing ([[observability]]).
- The tables that the collection pass reads. [[indexing-pipeline]],
  [[cc-pairs-and-creds]], [[permission-sync]], [[auth-and-identity]] and
  [[billing]] own them.

---

## Architecture

```
app / indexing thread ── emit_telemetry ──> BoundedTelemetry queue (in memory)
                                               │  daemon thread: enroll, gzip batch,
monitoring worker ── collect_fleet_telemetry ──┤  back off, retry, heartbeat
  (Lite: periodic_poller)  reads DB changes    └──> POST /v1/events (fleet service)
```

**One sender per process.** `utils/fleet_telemetry.py:start_telemetry`
creates one `BoundedTelemetry` and returns at once. These call it:
`onyx/main.py` for the API server,
`background/celery/apps/app_base.py` on worker ready, the Slack listener
(`onyxbot/slack/listener.py`), and a spawned docfetching process in
`background/indexing/job_client.py:_initializer`. The docfetching process uses
`report_process=False` and waits at most `EXIT_FLUSH_SECONDS` at exit.

**Emit is cheap.** `BoundedTelemetry.emit` runs `sanitize_data` and appends to a
bounded deque. It takes no lock and does no I/O. A full queue drops the event.
The daemon thread enrolls at `/v1/enroll` before its first batch, so startup
never waits for the database or the network. The service reply settles each
batch. The sender does not resend rejected events, and resends events the
service could not store at most `_MAX_RETRIES` times. Each heartbeat carries
the drop, reject and invalid counts.

**Emit points in application code.**
- Query timing: `utils/fleet_query_telemetry.py:telemetry_chat` wraps the chat
  entry points in `chat/process_message.py`. `telemetry_query` wraps the search
  API and the EE search stream. A 4xx `OnyxError`, which includes a query that
  a query-processing hook rejects, sends no event. In a chat turn,
  `chat/emitter.py:Emitter.emit` passes each packet to
  `QueryObservation.packet_queued`, `run_llm_loop` marks each LLM step through
  the `Emitter`, and the writer thread in `chat/process_message.py` calls
  `observe_packet` and `finish`.
- Indexing: `emit_stage_counter` from the fetch, embed and write steps
  (`background/indexing/run_docfetching.py:_timed_connector_runs`,
  `indexing/indexing_pipeline.py:embed_and_stream`,
  `document_index/opensearch/client.py:_report_written_chunks`). The sender
  thread sums deltas per attempt and stage.
- Answer votes: `db/feedback.py:create_chat_message_feedback` calls
  `utils/fleet_query_telemetry.py:emit_feedback` after the vote commits. The
  event carries the vote, the channel of the `MessageOrigin` that the caller
  passes, and a digest of the tenant and message id, which stays the same when
  the user votes again. Text-only feedback and follow-up requests send nothing.
- Queue depths: `background/celery/tasks/monitoring/tasks.py:_report_queue_depths`.
- OpenSearch health: `document_index/opensearch/resource_health.py:_report_to_fleet`.

**Collection.** `utils/fleet_telemetry_collector.py:collect_snapshots` runs
every five minutes per tenant (`collect_fleet_telemetry`, or
`background/periodic_poller.py:_run_fleet_telemetry` on Lite). It reads the
rows that changed since its cursor (index attempts with their errors and stage
metrics, and background jobs such as permission syncs, sync records and
hierarchy fetches), oldest first, plus work that is still running, under a
statement timeout (`db/fleet_telemetry.py:limit_statement_time`).
The cursor lives in the cache backend. `_send_in_order` decides where the next
pass resumes: at the first row the sender refused, or after a capped read. Work
goes out before the inventory (connectors, signup domains, license, the count
of standard user accounts), so a large inventory cannot hold it back. The pass
sends the whole inventory again when any part of it changes, and at least every
six hours. Event IDs come from row identity and update
time, so the fleet service drops repeats. Index attempt and job state reach the
fleet only from this pass.

**Identity.** `utils/fleet_telemetry.py:deployment_key` reads a random key from
`KVStore` (`db/fleet_enrollment.py:get_or_create_deployment_key`). Under
`MULTI_TENANT` it derives the key from `WEB_DOMAIN`, and
`BoundedTelemetry._envelope` reports each tenant as its own customer unless the
event is marked `shared`.

---

## Contracts and traps

1. `never-block-caller` **Telemetry never blocks or fails the caller.**
   `utils/fleet_telemetry.py:BoundedTelemetry.emit` does no lock or I/O, and
   `utils/fleet_telemetry.py:emit_telemetry` catches every exception. A new
   emit point must not read the database or call the network on an
   application or indexing thread. Put source reads in the collection pass.
2. `allowlisted-fields-only` **Only allowlisted fields leave the process.**
   `utils/fleet_telemetry.py:sanitize_data` drops an event with an unknown key, or a value that is not a
   number, a boolean or one short token with no spaces, slashes or `@`. A new
   key needs an entry in `utils/fleet_telemetry.py:_FIELDS`. Never send names,
   email addresses, URLs, paths, document content or exception text. Use
   `error_category`, which reads only the exception type name.
3. `fleet-service-accepts-first` **The fleet service must accept a new field
   before Onyx sends it.** The ingestion contract lives in the fleet service
   repository. Deploy the receiving change first, as
   `deployment/fleet-telemetry.md` notes for each optional field.
4. `forked-process-own-sender` **A forked process needs its own sender.**
   `emit` returns false when the sender's `pid` is not the current process. A
   new subprocess that emits events must call `start_telemetry` itself, as
   `background/indexing/job_client.py:_initializer` does.
5. `flush-before-os-exit` **Flush before `os._exit`.** A spawned docfetching
   process ends with `os._exit`, which skips the normal flush, so
   `background/celery/tasks/docfetching/tasks.py` calls
   `utils/fleet_telemetry.py:stop_telemetry` with
   `flush_timeout=EXIT_FLUSH_SECONDS` first. Keep that call
   before any new `os._exit`, or the last counters of the attempt are lost.
6. `collection-needs-sender` **The collection pass needs an enrolled sender in
   the same process.**
   `utils/fleet_telemetry_collector.py:collect_snapshots` returns silently when
   `get_sender()` is `None` or has not enrolled. Moving the task to a process that does not
   start a sender stops collection with no error.
7. `source-schema-change-silent` **A schema change in a table the pass reads
   fails no application test.** The pass catches the error and only counts it
   in the heartbeat (`source_errors`). When you rename or drop a column read
   in `db/fleet_telemetry.py`, run the collector tests in
   `backend/tests/external_dependency_unit/telemetry/`.
8. `telemetry-chat-keyword-args` **`telemetry_chat` reads its inputs from
   keyword arguments.** `utils/fleet_query_telemetry.py:_channel` and `_mode`
   read `new_msg_req` from the keywords. A caller that passes it by position
   reports channel `web` and mode `chat`, and nothing fails.
9. `discord-reports-api-channel` **Discord queries report channel `api`.**
   `server/query_and_chat/chat_backend.py:handle_send_chat_message` sets the
   origin to `api` for an API key or PAT caller, and the Discord bot calls it
   with an API key.
10. `connector-counts-reuse-admin-query` **Connector document counts reuse the
    admin page query.** `db/fleet_telemetry.py:connector_rows` calls
    `backend/onyx/db/document.py:get_document_counts_for_cc_pairs`, which
    counts indexed links and skips pending ones. Do not switch it to a stored
    counter on the pair.
11. `feedback-caller-passes-origin` **A feedback caller must pass its
    `MessageOrigin`.** The `origin` argument of
    `db/feedback.py:create_chat_message_feedback` defaults to `WEBAPP`. The
    Slack buttons in `onyxbot/slack/handlers/handle_buttons.py` pass
    `SLACKBOT`. The feedback endpoint passes nothing, so a vote through an API
    key or PAT reports channel `web`, unlike a query
    ([[#discord-reports-api-channel]]). A new caller that does not pass its
    origin reports `web`, and nothing fails.

---

## Decisions

- **State comes from database reads, not from emit points in each code
  path.** Index attempts and jobs change in many places. Reads in one pass keep
  database work off application threads ([[#never-block-caller]]), and a
  cursor lets that one reader see every change.
- **The schedule is fixed in code.** `COLLECTION_INTERVAL_SECONDS` and the
  other intervals are constants in `utils/fleet_telemetry.py`. The fleet
  service cannot change them.

---

## Known issues

- **A copied database reports as the same deployment.** The key lives in
  `key_value_store`. The operator must delete that row in the copy
  (`deployment/fleet-telemetry.md`).

---

## Dependencies

- [[background-jobs]]: the monitoring worker runs `collect_fleet_telemetry`, and the worker app base starts the sender of each worker.
- [[multi-tenancy]]: the pass runs per tenant, and the envelope scopes each tenant.
- [[indexing-pipeline]]: owns the index attempt tables the pass reads and the stage steps that emit counters.
- [[cc-pairs-and-creds]]: owns the connector rows in the inventory.
- [[permission-sync]]: owns the permission sync attempt rows the pass reads.
- [[auth-and-identity]]: owns the user rows behind the signup-domain values and the user count.
- [[chat-persistence]]: owns the feedback write that emits the answer vote.
- [[billing]]: owns the license row behind license presence.
- [[document-index]]: reports OpenSearch health and written chunks.

---

## Recipes

- `add-event-type` **Add an event type.** Add its keys to `_FIELDS` under a new type, and
  ship the fleet service change first. Copy `users` for a value that the
  collection pass reads, or `feedback` (`emit_feedback`) for a value already in
  memory. Until the fleet service accepts the type, it rejects the events and
  the sender drops them.
- `add-event-field` **Add a field to an event.** Add the key to `_FIELDS` (or `_NESTED_FIELDS`
  for a dict of numbers). Copy an existing optional field: find one with
  `grep -n optional deployment/fleet-telemetry.md`. Ship the fleet service
  change first ([[#fleet-service-accepts-first]]), and add the field to
  `deployment/fleet-telemetry.md`.
- `add-event-source` **Add an event source.** Emit from application code only when the value is
  already in memory; copy `document_index/opensearch/client.py:_report_written_chunks`.
  Otherwise add a capped, time-ordered query to `db/fleet_telemetry.py` (copy
  `job_rows`) and send it through `_send_in_order` in `collect_snapshots`. List
  the emit points with `git grep -n "emit_telemetry\|emit_stage_counter" backend`.
- `investigate-missing-event` **Investigate a deployment or an event that does
  not reach the fleet.**
  Check `DISABLE_TELEMETRY` on the service that should send it. Check that the
  process starts a sender ([[#forked-process-own-sender]],
  [[#collection-needs-sender]]). In the heartbeat, `dropped_events` counts
  every lost event, `invalid_events` counts the events that the allowlist
  dropped ([[#allowlisted-fields-only]]), and `source_errors` counts failed
  collection passes ([[#source-schema-change-silent]]).

---

## Verification

- Unit tests: the `test_fleet_*` files in `backend/tests/unit/onyx/utils/`.
- Collector against Postgres: `backend/tests/external_dependency_unit/telemetry/`.
