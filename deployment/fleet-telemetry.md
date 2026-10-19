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

Onyx Cloud derives its key from `WEB_DOMAIN`. Each Cloud tenant reports as a separate customer
inside the Cloud deployment.

## What Onyx sends

| Events | Source | When |
| --- | --- | --- |
| `runtime`, `version`, `resource`, `heartbeat` | Each API server, Celery worker, and Slack bot process | At start, then every 5 minutes |
| `query` | Chat turns and search requests: channel, mode, outcome, timing, error category, chat tool usage, LLM cycles | At the end of server execution |
| `attempt` counters | Indexing: documents fetched, chunks embedded and written, errors, durations | Summed for 30 seconds |
| `connector`, `tenant_domain`, `license` | Collector: connector settings and counts, signup email domains, license presence | On change, and every 6 hours |
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
first answer token. If no answer token arrived, the count includes every call. 1 means the model answered
directly. 2 means one round of tool calls came first. Text that a model streams before a tool call is the
first answer, so the count always matches the work that `first_answer_ms` measures. Model comparisons
report the count of the model that answered first. LLM calls inside tools do not count.

Deep research requests report the `deep_research` mode instead of `chat`. They report tool usage, but not
`llm_cycles`, because their orchestration is not a chat loop. Deploy the receiving server's optional
`llm_cycles` field and `deep_research` mode before this instrumentation.

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
the row identity and update time, so the fleet service drops the repeated events. Each read returns
the oldest changes first. When a read reaches its row limit, or the sender cannot take more events,
the next pass starts at the first row that this pass did not send.

## Cost and failure behavior

- Application threads only add an event to a bounded memory queue of 2048 events. They take no
  lock and do no network, disk, or database work. When the queue is full, Onyx drops the event.
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
  backend/tests/unit/onyx/utils/test_fleet_telemetry_collector.py \
  backend/tests/unit/onyx/utils/test_fleet_enrollment.py
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/telemetry/test_fleet_collector.py
```

The second command needs a migrated PostgreSQL. It copies the source tables into a temporary
schema, reads it as a tenant, and removes it.
