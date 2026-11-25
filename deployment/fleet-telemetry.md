# Fleet telemetry

Each Onyx deployment sends usage and health data to `https://telemetry.onyx.app`.
The fleet service, its dashboard, and its storage are in
[`onyx-dot-app/fleet-management-service`](https://github.com/onyx-dot-app/fleet-management-service).
Fleet telemetry is the only usage reporting in Onyx. Cloud PostHog analytics and Sentry are separate.

## Turn it off

Set `DISABLE_TELEMETRY=true` on all Onyx services and restart them. In Helm, set
`configMap.DISABLE_TELEMETRY: "true"`. With this setting, no process starts a sender, and the
collection task is not scheduled.

`ONYX_TELEMETRY_ENDPOINT` changes the destination. Use it only for tests.

## Deployment identity

On first start, Onyx creates one random key in the `key_value_store` table, under
`fleet_telemetry_deployment_key`. The key stays the same across restarts and upgrades. The sender
gives the key to `/v1/enroll`, and the fleet service answers with the deployment's IDs.

A copy of the database reports as the same deployment. To make the copy a new deployment, delete
that row in the copy before it starts.

A deployment upgraded from before v5 also has the instance UUID that the old anonymous telemetry
sent (encrypted key-value `customer_uuid`). The sender adds it to `/v1/enroll` as
`legacy_customer_uuid`, so the fleet service can link the deployment to its pre-v5 records. Onyx
never creates this UUID for enrollment. If the service answers 422, the sender enrolls again
without the field.

Onyx Cloud derives its key from `WEB_DOMAIN`. Each Cloud tenant reports as a separate customer
inside the Cloud deployment.

## What Onyx sends

| Events | Source | When |
| --- | --- | --- |
| `runtime`, `version` | Each API server, Celery worker, and Slack bot process. `version` is the release tag; other builds (nightly, edge, dev builds) send their short commit | At start |
| `resource`, `heartbeat` | Each API server, Celery worker, and Slack bot process | Every 5 minutes |
| `query` | Chat turns and search requests: channel, mode, outcome, timing, error category, chat tool usage, LLM cycles | At the end of server execution |
| `attempt` counters | Indexing: documents fetched, chunks embedded and written, errors, durations | Summed for 30 seconds |
| `connector`, `tenant_domain`, `license`, `users` | Collector: connector settings and counts, permission and group sync times and cadence of permission-synced connectors, signup email domains, license presence, the number of standard user accounts and how many of them are active | Each item when it changes, and 6 hours after its own last send |
| `feedback` | A thumbs up or down on an answer: the vote, the channel, and a digest of the answer id | When a user votes |
| `failure_counts` | Each API server, Celery worker, and Slack bot process: failed logins by method, and MCP server discovery and setup check failures | With the heartbeat, every 5 minutes, only when a count is not zero |
| `attempt`, `stage`, `job` | Collector: index attempts, stage timings, sync and migration jobs that changed | Every 5 minutes |
| `heartbeat` deployment fields | API: Standard or Lite; collector: whether a configured connector has an indexed document | Every 5 minutes |
| `queue` | Celery queue depths, from the queue monitor | Every 10 minutes |
| `resource` (OpenSearch) | Cluster status, shard counts, and pressure flags, from the resource health check | With each check |

Chat queries report `tool_usage`: `none`, `search_only`, `other_only`, or `search_and_other`.
Search means the built-in internal search tool. Web search, custom tools, and MCP tools count as other tools.
Usage records tools when execution starts, including failed calls. Internal reasoning and research orchestration do not count as tools.
Repeated calls and nested research calls share one classification. Model comparisons combine usage across all models.
The server emits one query event when execution ends, even if the client disconnects and reconnects.
Cancellation freezes usage at the server's stop point. Search-mode requests leave this chat classification unset.
Outcome remains separate from tool usage. Deploy the receiving server's optional `tool_usage` field before this instrumentation.

Chat queries report `llm_cycles`: the chat-loop LLM calls up to and including the call that produced the
first answer token. 1 means the model answered directly. 2 means one round of tool calls came first. Text
that a model streams before a tool call is the first answer, so later calls do not count. The two values
use different measurement points. The emitter records `llm_cycles` when the worker queues the first answer
text. `first_answer_ms` is recorded when the stream writer reads that text, so it also includes any writer
delay. A slow writer can increase `first_answer_ms`, but it cannot change `llm_cycles`. Model comparisons
report the count of the model that answered first. If no answer token arrived, the count is the highest
number of calls that one model made: the models run in parallel, so their counts are not added. LLM calls
inside tools do not count.

Deep research requests report the `deep_research` mode instead of `chat`. They report tool usage, but not
`llm_cycles`, because their orchestration is not a chat loop. Deploy the receiving server's optional
`llm_cycles` field and `deep_research` mode before this instrumentation.

A failed query reports a fixed `error_code` and an `error_source`. `llm` means the error came from the
LLM provider. `onyx` means it came from Onyx. LLM failures also report `llm_provider`, the provider type
(for example `openai` or `bedrock`). A provider that is not a known type reports `custom`, so provider names
never leave the deployment. LLM categories include `auth`, `rate_limit`, `quota`, `not_found` (a model or
deployment that the provider does not know), `context_limit`, `content_policy`, `bad_request` and
`source_unavailable`. Bad input and missing permissions do not count as failed queries. Onyx rate limits,
seat limits and inactive subscriptions do count, as `rate_limit` and `license`. Deploy the receiving
server's `error_source` and `llm_provider` fields and these categories before this instrumentation.

Queries also count their tool calls. `tool_calls` and `tool_failures` give the number of calls and failed
calls for each tool kind: `search`, `web_search`, `open_url`, `mcp`, `custom` (custom and OpenAPI actions),
`image`, `python`, `code_mode`, `sandbox`, and `other`. The kind comes from the tool's class, never from
its name. A failed call is a call that raised an error or returned an error result to the model.
`mcp_auth_failures` counts MCP calls that the server refused for authentication. A query without tool
calls omits these fields. Deploy the receiving server's `tool_calls`, `tool_failures` and
`mcp_auth_failures` fields before this instrumentation.

Login and MCP failures outside a query go into one in-memory count for each process. The process sends
the counts with its heartbeat in one `failure_counts` event, and then sets them to zero. A process with
no failures in the window sends no event. `login_failures` counts failed sign-ins by method: `password`,
`oauth` (the Google login configured by environment variables), `oidc` (OIDC and Google provider rows),
and `saml`. `mcp_failures` counts `discovery_auth`, `discovery_timeout` and `discovery_error` when Onyx
lists the tools of an MCP server, and `probe_unreachable` and `probe_blocked` when the setup check cannot
reach a server. Each count stops at 100,000 for each window, so many failed logins never add events or
bytes. Deploy the receiving server's `failure_counts` event type before this instrumentation.

Connector document counts use the same query as the connector admin page. They count indexed
document links for each connector and credential pair, excluding pending links. Counts follow
indexing and deletion directly; they do not use the pair's legacy stored counter.

Only the API reports deployment type, using `DISABLE_VECTOR_DB` to distinguish Lite from Standard.
Workers and standalone collectors omit type because their settings can differ from the API's.
The connector flag checks indexed document links for existing connector/credential pairs, excluding
the seeded upload connector. Empty connectors and raw library uploads do not qualify. The check
is independent of the 1000-row inventory cap and remains subject to the statement timeout.

Onyx never sends names, paths, URLs, email addresses, user IDs, document content, query text, or
error messages. Each event type has a list of permitted keys. A value must be a number, a boolean,
or one short token without spaces, slashes, or `@`. The sender drops all other events.

## Where collection runs

The `collect_fleet_telemetry` Celery task runs on the monitoring worker every 5 minutes for each
tenant. Onyx Lite has no Celery workers, so the API server's periodic poller runs the same pass.
Telemetry needs no extra container, Helm value, or migration.

Each pass reads the rows that changed since the previous pass, and all work that is still running.
It reads 5 minutes of the previous window again, for rows that committed late. Event IDs come from
the row identity and the time of its state, so the fleet service drops the repeated events. Running
attempts and jobs go out at revision 0. A finished one goes out at its end, at a higher revision,
so the service orders runs by when they ended. It goes out again only when a late batch or a
rewritten final status changes it. Each read returns
the oldest changes first. When a read reaches its row limit, or the sender cannot take more events,
the next pass starts at the first row that this pass did not send.

## Cost and failure behavior

- Application threads only add an event to a bounded memory queue of 2048 events. They take no
  lock and do no network, disk, or database work. When the queue is full, Onyx drops the event.
- A login or MCP failure only adds one to a count in memory, under a short lock.
- One daemon thread in each process sends gzip batches of up to 100 events every 2 seconds.
- During an outage, the sender keeps the current batch and waits up to about 4 minutes between
  attempts. The sender does not send rejected events again. When the fleet service cannot store
  an event yet, the sender sends it again after a backoff, at most 3 times.
- Each collection pass uses one transaction. Each statement stops after 1.5 seconds and reads at
  most 1000 rows. A failed pass adds a source error to the heartbeat and reads the same window again
  on the next pass. A pass that was stopped early continues on the next pass, so rows are not skipped.
- Short-lived indexing processes wait at most 2 seconds at exit for their last delivery.
- Readiness, requests, and indexing never wait for telemetry.

## Tests

```sh
uv run pytest backend/tests/unit/onyx/utils/test_fleet_telemetry.py \
  backend/tests/unit/onyx/utils/test_fleet_failure_counts.py \
  backend/tests/unit/onyx/utils/test_fleet_telemetry_collector.py \
  backend/tests/unit/onyx/utils/test_fleet_enrollment.py
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/telemetry/test_fleet_collector.py
```

The second command needs a migrated PostgreSQL. It copies the source tables into a temporary
schema, reads it as a tenant, and removes it.
