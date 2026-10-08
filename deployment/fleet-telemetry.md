# Fleet telemetry

The central Fleet Management Service, dashboard, archive and AWS stack live in
[`onyx-dot-app/fleet-management-service`](https://github.com/onyx-dot-app/fleet-management-service).
This repository owns application hooks and the source collector implementation.
Fleet telemetry is the only usage reporting in Onyx. Cloud PostHog analytics, Sentry, and local
timing logs are separate from it.

The API server, Celery workers, the Slack bot, and the collector each put reviewed fields into one
bounded memory queue per process.
Emissions take no lock and perform no database, network, disk, serialization, or logging operations.
A full queue and disabled collection drop events without waiting.
One sender retries retained batches with stable IDs and exponential backoff during outages.
It reuses an HTTP session and gzip-compresses batches at level 1 in its background thread.
A backlog drains in up to five 100-event batches per two-second wakeup.
Events that the service answers with `retry` go out again with the next batch. After five sends
they are dropped, so they cannot hold back newer events. Outages do not count against this limit.
Batch indexing counters are combined by attempt and stage for up to 30 seconds (at most 256
active keys). Error counters bypass this window. No aggregation or compression runs on
application request or indexing threads.
At shutdown, the sender releases all combined counters. Its thread then sends the remaining
batches for at most five seconds and stops at the first incomplete delivery.
Long-running services do not wait for it. Spawned docfetching processes wait at most two
seconds, so their final counters are not lost when they exit. Query events can be lost during outages.
Attempt and job state comes from source rows that the separate collector reads. Only those rows
carry the connector identity that the service requires for attempt state.

Connector metadata contains reviewed booleans, numbers, selection counts, and a time-filter flag.
It excludes connector names, folder names, paths, URLs, credentials, and document content.
The configuration fingerprint describes structural settings. It cannot distinguish folders with equal counts.
Error samples are read locally with a size limit. Only fixed error categories and keyed fingerprints leave the collector.
Installation fingerprints use a separate privacy key. The enrollment credential cannot derive this key.

## Automatic collection

New installations start reporting to `https://telemetry.onyx.app` without operator provisioning.
Startup of each sending service schedules background enrollment and returns immediately.
Until the local identity is ready, hooks drop observations; startup never waits for telemetry.
Identity storage first waits until the process selects its edition. Each process caches its
secret codec on first use, and a spawned docfetching child selects its edition after it starts.
An earlier seed read would cache the Community codec and break connector credential decryption there.
The standalone collector selects its edition at startup, like every other Onyx process.
A background connection creates one random seed in the existing encrypted key-value store.
Concurrent processes use an atomic insert and read the same stored seed.
Storage uses Onyx's existing secret encryption configuration; community installations have its existing encryption limitations.
The credential and privacy key use distinct HMAC derivations. The privacy key never leaves Onyx.
The database survives process, container, and pod restarts, so deployment identity stays stable.
A database clone shares this identity. For an independent clone, remove only the
`fleet_telemetry_installation_seed_v1` entry from its encrypted key-value store before startup.
A fresh database gets a fresh identity. No new migration is needed for identity storage.

The sender registers its credential at `/v1/enroll` before its first batch.
The service derives the deployment namespace from the credential and stores only its hash.
The response contains identity fields only. It cannot change source settings or instruct the deployment.
Unavailable storage or collection endpoints trigger bounded background retries with backoff.
Neither API readiness nor indexing depends on successful enrollment or delivery.

Docker Compose starts a separate collector with a 0.2 CPU and 256MiB memory cap.
Helm also runs it by default, with 200m CPU and 256Mi memory limits in
`fleetTelemetry.collector.resources`. Place the Helm collector with `fleetTelemetry.collector`
`nodeSelector`, `tolerations`, `affinity`, and `podAnnotations`; it uses the chart's `imagePullSecrets`.
On a backend image older than the collector, the Compose and Helm collector waits idle and
does not restart. Thus a chart or Compose file that is newer than its image does not cause a
crash loop or a failed `--wait`.
The collector uses standard Onyx PostgreSQL, Redis, and OpenSearch settings by default.
With `DISABLE_VECTOR_DB=true` (Onyx Lite), it does not read OpenSearch or Celery queues.
The Lite Compose overlay sets this value on the collector too.
All collection transactions are read-only, with short statement and lock limits.
The startup identity write uses a separate connection that is closed before collection begins.
For stricter database permissions, supply a dedicated read-only collector URL as described below.
Custom manifests must run `python -m onyx.utils.fleet_telemetry_collector` in a separate
container for periodic snapshots. Application hooks enroll automatically when the instrumented
services start.

Multi-tenant automatic collection namespaces each logical deployment under its installation identity.
An automatically enrolled credential cannot write into another installation's namespace or grant
trusted Cloud policy inheritance. Existing operator-issued Cloud credentials keep their current identity mapping.
Automatic Cloud enrollment requires the standard schema's encrypted key-value table and database access.
Redis IAM and Sentinel topologies need an explicit supported collector connection; they are not inferred.

**Release order:** deploy the fleet service with `/v1/enroll` before releasing this Onyx version.
Merging source code alone does not update existing running containers or the collection service.

## Configuration

No fleet identity variables are required for automatic collection.
Set `DISABLE_TELEMETRY=true` to opt out. Helm also supports `fleetTelemetry.enabled=false`.
An endpoint override is optional; TLS is required outside approved local test hosts.
In Helm, set the endpoint with `fleetTelemetry.endpoint`. The chart sets
`ONYX_TELEMETRY_ENDPOINT` itself, so a value in the ConfigMap or `extraEnvFromSecret` has no effect.
To retain operator-provisioned identity, supply all four identity/authentication variables together.
A partial override fails closed and does not create another installation.
In Helm, set `fleetTelemetry.customerUuid` and `fleetTelemetry.deploymentId`, and put
`ONYX_TELEMETRY_TOKEN` and `ONYX_TELEMETRY_PRIVACY_KEY` in `fleetTelemetry.existingSecret`.
The chart rejects `deploymentId` without `customerUuid`.

These optional variables apply to every service that sends telemetry: the API server, Celery
workers, the Slack bot, and the collector. Helm sets the endpoint and identity variables only on
those workloads.

- `ONYX_TELEMETRY_ENDPOINT`: HTTPS base URL. Local tests may use plain HTTP to `localhost` or `127.0.0.1`.
- `ONYX_TELEMETRY_TOKEN`: scoped customer or Cloud deployment token.
- `ONYX_TELEMETRY_CUSTOMER_UUID`: registered installation UUID.
- `ONYX_TELEMETRY_DEPLOYMENT_ID`: opaque deployment identifier.
- `ONYX_TELEMETRY_INSTANCE_DOMAIN`: optional instance host; defaults to `WEB_DOMAIN`.
  Startup canonicalizes the host and stores only its installation-keyed HMAC in telemetry.
- `ONYX_TELEMETRY_PRIVACY_KEY`: separate random installation key with at least 32 characters.
- `DISABLE_TELEMETRY=true`: disable fleet enrollment, collection, and sending.
  This takes precedence over valid fleet credentials and enablement settings.
  Set it on all application services and separately deployed collector containers, then restart them.
  Disabled collectors do not create sender threads or read PostgreSQL, Redis, Kubernetes, OpenSearch, or AWS.
  A long-running disabled collector waits idle for shutdown; `--once` exits successfully.
  In Helm, set `configMap.DISABLE_TELEMETRY: "true"`. This also omits fleet collector workloads and RBAC.
  Compose services read the value from their deployment environment file.

Rotate `ONYX_TELEMETRY_DEPLOYMENT_ID` whenever a source database is reset or replaced.
This prevents reused numeric connector/attempt IDs from merging with the prior installation.

The following variables belong to the isolated collector rather than the application services:

| Variable | Default / purpose |
| --- | --- |
| `ONYX_TELEMETRY_DATABASE_URL` | Optional read-only PostgreSQL DSN; otherwise use standard Onyx settings. |
| `ONYX_TELEMETRY_REDIS_URL` | Optional Redis DSN for queue reads. Without it, only an automatically enrolled collector on shard zero reads queues, with the standard Redis broker settings. |
| `ONYX_TELEMETRY_SCHEMAS` | Comma-separated explicit schemas. Default: `POSTGRES_DEFAULT_SCHEMA` (`public`) in single-tenant mode. Omit it in multi-tenant mode to discover tenant schemas. |
| `ONYX_TELEMETRY_SCHEMA_SHARD_COUNT` | `1`; number of stable source-schema partitions, capped at 1,000. |
| `ONYX_TELEMETRY_SCHEMA_SHARD_INDEX` | `0`; this collector's partition within the configured count. |
| `ONYX_TELEMETRY_KUBERNETES` | Disabled unless `true` (the Helm default); namespace-scoped pod/metrics collection. |
| `ONYX_TELEMETRY_KUBERNETES_NAMESPACE` | `default`; Helm injects the actual namespace. |
| `ONYX_TELEMETRY_KUBERNETES_API_URL` | Optional HTTPS API endpoint override for local testing. |
| `ONYX_TELEMETRY_KUBERNETES_TOKEN_FILE` | Default mounted service-account token; optional token-file override. |
| `ONYX_TELEMETRY_KUBERNETES_CA_FILE` | Default mounted service-account CA; optional CA-file override. |
| `KUBERNETES_SERVICE_HOST` / `KUBERNETES_SERVICE_PORT_HTTPS` | Injected by Kubernetes; API host and HTTPS port (`443`). |
| `ONYX_TELEMETRY_AWS_RESOURCES_JSON` | Optional inline JSON inventory for managed CloudWatch resources; omit to disable. |
| `AWS_REGION` | AWS SDK region, default `us-east-2` for the telemetry adapter. |

In Helm, put the optional `ONYX_TELEMETRY_DATABASE_URL` and `ONYX_TELEMETRY_REDIS_URL` keys in
`fleetTelemetry.existingSecret`. Automatic enrollment still applies.
`ONYX_TELEMETRY_DISK_MOUNT` optionally selects the mount used for process disk metrics;
the default is `/`. This affects background resource reads only.
Collector-specific variables are tracked in the repository environment baseline;
the optional application identity/auth overrides are documented in Compose env templates.

### Source reads

One source connection has a two-second connect timeout, 1.5-second statement limit, and 100ms lock limit.
Reads use pages of 200 rows. Unavailable sources back off independently.
The collector scans up to ten schemas per tick with a one-second wall budget.
Attempt and job history starts 184 days back, inside the service's 190-day horizon.
At the live edge, the next read starts ten minutes before the previous read, on the source clock.
This catches rows that commit late. A 24-hour repair sweep runs every six hours and after
deferred events expire. Durable event IDs let the service deduplicate these overlaps.
A separate bounded pass rereads jobs that are not started or in progress, including long-running
permission and group syncs that started before the repair window. Changed state or counts get
distinct safe event identities; terminal snapshots retain source timestamps and identities.

Collection schedules are source-owned. The collector never fetches fleet-service settings.
The intervals are five minutes for connectors/resources and ten minutes for queues.
With Kubernetes collection, pod lists are read every 30 seconds and pod metrics every five minutes.
Collector health reports every five minutes and immediately on a failure-level transition.
License snapshots and signup-domain metadata are sent when changed, after observed delivery loss,
and at least every six hours while connected. The source still reads them on its normal schedule;
license set/remove events are sent immediately. The metadata cache is capped at 20,000 entries.

### Shards

Cloud shard collectors need topology-specific placement: deploy collectors per physical database shard.
Split a large database with `ONYX_TELEMETRY_SCHEMA_SHARD_COUNT` and `ONYX_TELEMETRY_SCHEMA_SHARD_INDEX`.
Stable hash partitions avoid duplicate source collectors. Ten collectors cover 1,000 tenants conservatively.
Each collector discovers new tenant schemas every minute when explicit schemas are absent.
Only one designated collector should report shared queues and AWS infrastructure.
Omit Redis URLs and AWS resource configuration from other replicas. Automatic queue discovery runs only on shard zero.
The collector uses the same backend image as the application, avoiding a separate dependency set.
The Helm chart runs one collector. Set its `collector.schemaShardIndex` and
`collector.schemaShardCount`, and run the other shards from separate manifests.
Use `fleetTelemetry.collector.image` only for a compatible backend-image override.
Leave `collector.schemas` empty to read the default schema (single tenant) or to discover
tenant schemas (multi-tenant).

### Kubernetes

Set `ONYX_TELEMETRY_KUBERNETES=true` for namespace-scoped pod health and resource reads.
Helm sets it by default through `fleetTelemetry.collector.kubernetes`, and creates a Role that
can only list pods and pod metrics in the release namespace.
Pod, namespace, and container identities are keyed hashes. Status messages and environment variables are excluded.
Version reads emit only approved version syntax and SHA256 image digests when a container image changes.
Repository names and unrecognized image tags are excluded.
Runtime records include lifetime `restart_count` and newly observed `restart_delta`.
A ready container's historical restart/OOM state does not produce a fresh failure on collector startup.
Pod reads use 25-item pages and a 1MiB response bound. Missing metrics leave resource values unavailable.
For local Kubernetes access, explicit API URL, token-file, and CA-file variables are supported.

### TLS and credentials

Automatic connections inherit standard PostgreSQL and Redis TLS options, including client certificates.
The Helm collector mounts the configured PostgreSQL and Redis CA sources.
Mount client certificates and keys at their configured paths when using custom manifests.
Explicit telemetry database and Redis URLs must include their own TLS options.
The Helm collector runs as non-root on a read-only root filesystem, so it cannot run
`update-ca-certificates`. With `customCACerts.enabled`, an init container adds the custom roots
to a copy of the system bundle instead.
With `USE_IAM_AUTH=true`, the collector needs AWS credentials for database tokens. The Helm
collector uses its own ServiceAccount and disables the EC2 instance metadata service, so give it
IRSA through `fleetTelemetry.collector.serviceAccountAnnotations`. The Compose collector receives
the same IAM and AWS settings as the API server.

### Managed AWS resources

The isolated collector reads at most 32 resource targets in one bounded CloudWatch request.
Targets specify `kind` (`rds`, `elasticache`, or `opensearch`), `resource_id`, and reviewed
`cpu_limit_cores`, `memory_limit_bytes`, or `disk_limit_bytes` for the same instance scope.
Redis requires `node_id`; OpenSearch requires `node_id` and `account_id`.
Raw identifiers remain local. The collector emits fixed service roles and keyed IDs.
Missing metrics or allocations stay unavailable. RDS memory use is derived from freeable memory;
Redis memory describes engine capacity, and OpenSearch memory describes operating-system utilization.
In Helm, enable `collector.awsResources` on one collector and put the JSON in
`fleetTelemetry.existingSecret` under `ONYX_TELEMETRY_AWS_RESOURCES_JSON`.
Use `collector.serviceAccountAnnotations` for a narrow CloudWatch read role through IRSA.

## Read-only source grants

Create the role with your secret manager. Do not place its password in repository SQL.
Apply these grants to each source schema. Replace `public` with the intended schema.

```sql
GRANT CONNECT ON DATABASE onyx TO onyx_fleet_reader;
GRANT USAGE ON SCHEMA public TO onyx_fleet_reader;
GRANT SELECT ON public.connector,
    public.connector_credential_pair,
    public.index_attempt,
    public.index_attempt_errors,
    public.index_attempt_stage_metric,
    public.sync_record,
    public.doc_permission_sync_attempt,
    public.external_group_permission_sync_attempt,
    public.hierarchy_fetch_attempt,
    public.port_attempt,
    public.fleet_signup_email_domains,
    public.fleet_license_state
TO onyx_fleet_reader;
ALTER ROLE onyx_fleet_reader SET default_transaction_read_only = on;
ALTER ROLE onyx_fleet_reader SET statement_timeout = '1500ms';
ALTER ROLE onyx_fleet_reader SET lock_timeout = '100ms';
ALTER ROLE onyx_fleet_reader CONNECTION LIMIT 2;
```

The domain-only view is created by migration `b67c3fa177d6`. It exposes signup domains and
their earliest account creation timestamps. It excludes bot, external-permission, anonymous,
and service accounts. The view owner needs user-table access; the collector does not.

Do not grant access to credentials, users, document contents, file storage, or chat message tables.
Avoid `GRANT SELECT ON ALL TABLES` and blanket default privileges.
Provision these grants for new tenant schemas through the existing tenant provisioning process.
The two-connection role limit assumes one collector uses the role. For multiple
collectors, use separate roles or raise this limit to twice the configured collector count.

## Signup domain identity

Registration enqueues a `tenant_domain` event with a normalized email domain and signup timestamp.
This uses the existing nonblocking sender and performs no telemetry network or database reads.
The isolated collector reconciles the domain-only view on the connector collection cadence,
with the source read limits above. Missing view permissions increment `email_domain_errors`
without stopping connector collection. Full email addresses and local parts never enter these events.

Existing accounts use their database creation timestamps. Historical timestamp ties cannot
prove signup order. Accounts deleted before either collection path ran cannot be recovered.
The fleet service retains domains after collection and recommends the earliest signup domain.
Operators explicitly apply that domain as the tenant label; classification is independent.

## License presence

Migration `93b903235ac2` creates `fleet_license_state`. Grant SELECT on the view only.
It exposes a boolean and a first stored timestamp, never the signed blob or billing information.
The standalone collector reads it every connector interval and reports `license_errors` on failure.
License set/removal hooks enqueue after commit, with no additional database or network request.
A configured license sets the automatic registry default to Customer; absent means Free User.
Operator POC/Customer/Free User tags take precedence. Presence does not establish validity or expiry.

## OpenSearch health and native stage summaries

Collector shard zero checks OpenSearch once per resource interval. It uses the same OpenSearch
connection settings as Onyx, with a two-second request timeout and no retries. It reads the existing
shared Redis resource-health snapshot with a 200ms timeout; configure the standard Onyx Redis
connection variables on the collector too. The OpenSearch identity needs cluster-health read access.
Only cluster status, counts and pressure flags leave the process. Node/index/cluster names and raw
errors are excluded. A failed check reports unavailable, while missing/stale cached pressure stays
unknown. All checks run in the isolated collector, outside application requests and indexing work.

The collector also reads `index_attempt_stage_metric`, which Onyx already maintains. Migration
`fb47e93126e7` adds a concurrent `(time_last_event,id)` index. Grant the collector SELECT on this
table as above. Changed summaries are read in 200-row pages on the connector interval, with 29-day
initial backfill (inside the service's 30-day horizon) and a five-minute reconciliation overlap.
Events carry the canonical stage, attempt/connector IDs, count, duration sum/min/max/M2, and
first/last sample times. They contain no document or source labels.
This adds no per-document emit calls and cannot block application threads.

The fleet service keeps these summaries, and the indexing counter deltas from senders, in
short-lived storage: 30-day queryable retention, no cold archive. Attempt outcomes and document
totals keep their existing history policy.

## Reported versions and health

Development builds report `dev`. Release builds use the existing `ONYX_VERSION`.
Set optional `ONYX_BUILD_SHA` to the build's lowercase hex Git commit (7–40 characters)
to identify the source revision. Invalid values are omitted; telemetry does not invoke Git.
Heartbeat delivery counters separate recent loss from cumulative drops, local validation
failures, and server rejections. Queues remain bounded and lossy across process termination.
Connector jobs include the integration ID when their source table identifies it.
Job events carry processed counts, but no expected totals and no progress timestamp. The service
therefore shows a job that runs longer than 15 minutes as "progress unknown" (a warning), not as stalled.

## Verification

Unit tests cover strict privacy validation, fault isolation, lock-free emission, bounded queues,
partial HTTP acknowledgments, stable retry IDs, deferred-event expiry, backlog draining, bounded
final delivery, first-answer timing, and OpenSearch item acknowledgments.
They also verify Kubernetes resource denominators and content exclusion.

Run the source tests against a migrated database. They use the standard Onyx PostgreSQL
settings; set `ONYX_TELEMETRY_TEST_DB` to use another database:

```sh
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/telemetry/test_fleet_collector.py
```

The tests create and remove an isolated schema. They check 250 connectors,
terminal failures, permission/group syncs, source read-only enforcement, and schema validation.
