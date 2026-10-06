# Fleet telemetry

The central Fleet Management Service, dashboard, archive and AWS stack live in
[`onyx-dot-app/fleet-management-service`](https://github.com/onyx-dot-app/fleet-management-service).
This repository owns application hooks and the source collector implementation.
Telemetry environment variables and the ingestion contract retain their names for compatibility.

The API and workers emit reviewed fields into one bounded memory queue per process.
Emissions perform no database, network, disk, serialization, or logging operations.
Queue contention, overload, and disabled collection drop events without waiting.
One sender retries retained batches with stable IDs and exponential backoff.
Shutdown does not wait for the sender. Query events can be lost during outages.
Terminal attempts and jobs are recovered from authoritative source rows by a separate collector.

Connector metadata contains reviewed booleans, numbers, and selection counts.
It excludes connector names, folder names, paths, URLs, credentials, and document content.
The configuration fingerprint describes structural settings. It cannot distinguish folders with equal counts.
Error samples are read locally with a size limit. Only fixed error categories and keyed fingerprints leave the collector.
Installation fingerprints require a separate random privacy key. Do not reuse the central authentication token.

## Configuration

Set these variables on API pods, workers, and the collector:

- `ONYX_TELEMETRY_ENDPOINT`: HTTPS base URL. Local tests also accept localhost or the `telemetry` Compose service.
- `ONYX_TELEMETRY_TOKEN`: scoped customer or Cloud deployment token.
- `ONYX_TELEMETRY_CUSTOMER_UUID`: registered installation UUID.
- `ONYX_TELEMETRY_DEPLOYMENT_ID`: opaque deployment identifier.
- `ONYX_TELEMETRY_INSTANCE_DOMAIN`: optional instance host; defaults to `WEB_DOMAIN`.
  Startup canonicalizes the host and stores only its installation-keyed HMAC in telemetry.
- `ONYX_TELEMETRY_PRIVACY_KEY`: separate random installation key with at least 32 characters.
- `DISABLE_TELEMETRY=true`: disable the fleet sender.

Rotate `ONYX_TELEMETRY_DEPLOYMENT_ID` whenever a source database is reset or replaced.
This prevents reused numeric connector/attempt IDs from merging with the prior installation.

The collector also needs `ONYX_TELEMETRY_DATABASE_URL`, with a read-only PostgreSQL role.
Use `ONYX_TELEMETRY_REDIS_URL` for queue depth and `ONYX_TELEMETRY_SCHEMAS` for explicit schemas.
Run `python -m onyx.utils.fleet_telemetry_collector` in a separate container.
One source connection has a two-second connect timeout, 1.5-second statement limit, and 100ms lock limit.
Reads use pages of 200 rows. Unavailable sources back off independently.
The collector scans up to ten schemas per tick with a one-second wall budget.
Completed attempt/job repair sweeps wait for the configured connector interval.
A separate bounded active-job pass includes long-running permission/group jobs
whose start timestamp predates the recent repair window. Changed state/counts get
distinct safe event identities; terminal snapshots retain source timestamps and identities.

For Cloud, deploy collectors per physical database shard.
Split a large database with `ONYX_TELEMETRY_SCHEMA_SHARD_COUNT` and `ONYX_TELEMETRY_SCHEMA_SHARD_INDEX`.
Stable hash partitions avoid duplicate source collectors. Ten collectors cover 1,000 tenants conservatively.
Each collector discovers new tenant schemas every minute when explicit schemas are absent.
Only one designated collector should report shared queues and AWS infrastructure.
Omit their Redis URL and AWS resource configuration from other replicas.
In Helm, set `fleetTelemetry.collector.image` to the standalone image and set
`schemaShardIndex`/`schemaShardCount` for each collector. Empty `collector.schemas`
enables discovery for Cloud instead of restricting collection to `public`.

The server config controls connector, queue, and resource upload intervals.
Configuration reads run in the sender worker every minute. Each interval has a 60–3,600 second local bound.
The defaults are five minutes for connectors/resources and ten minutes for queues.

Enable `ONYX_TELEMETRY_KUBERNETES=true` for namespace-scoped pod health and resource reads.
The Helm collector Role permits only pod and pod-metrics reads in its namespace.
Pod, namespace, and container identities are keyed hashes. Status messages and environment variables are excluded.
Version reads emit only approved version syntax and SHA256 image digests when a container image changes.
Repository names and unrecognized image tags are excluded.
Runtime records include lifetime `restart_count` and newly observed `restart_delta`.
A ready container's historical restart/OOM state does not produce a fresh failure on collector startup.
Pod reads use 25-item pages and a 1MiB response bound. Missing metrics leave resource values unavailable.
For local Kubernetes access, explicit API URL, token-file, and CA-file variables are supported.

The following advanced variables belong to the isolated collector rather than application Compose configuration:

| Variable | Default / purpose |
| --- | --- |
| `ONYX_TELEMETRY_DATABASE_URL` | Required read-only PostgreSQL DSN; provide through a secret. |
| `ONYX_TELEMETRY_REDIS_URL` | Optional Redis DSN; omit on collectors that should not report shared queues. |
| `ONYX_TELEMETRY_SCHEMAS` | Comma-separated explicit schemas; default `public`. Omit in Cloud to enable discovery. |
| `ONYX_TELEMETRY_SCHEMA_SHARD_COUNT` | `1`; number of stable source-schema partitions, capped at 1,000. |
| `ONYX_TELEMETRY_SCHEMA_SHARD_INDEX` | `0`; this collector's partition within the configured count. |
| `ONYX_TELEMETRY_KUBERNETES` | Disabled unless `true`; namespace-scoped pod/metrics collection. |
| `ONYX_TELEMETRY_KUBERNETES_NAMESPACE` | `default`; Helm injects the actual namespace. |
| `ONYX_TELEMETRY_KUBERNETES_API_URL` | Optional HTTPS API endpoint override for local testing. |
| `ONYX_TELEMETRY_KUBERNETES_TOKEN_FILE` | Default mounted service-account token; optional token-file override. |
| `ONYX_TELEMETRY_KUBERNETES_CA_FILE` | Default mounted service-account CA; optional CA-file override. |
| `KUBERNETES_SERVICE_HOST` / `KUBERNETES_SERVICE_PORT_HTTPS` | Injected by Kubernetes; API host and HTTPS port (`443`). |
| `ONYX_TELEMETRY_AWS_RESOURCES_JSON` | Optional JSON inventory or `@file` reference for managed CloudWatch resources; omit to disable. |
| `AWS_REGION` | AWS SDK region, default `us-east-2` for the telemetry adapter. |

`ONYX_TELEMETRY_DISK_MOUNT` optionally selects the mount used for process disk metrics;
the default is `/`. This affects background resource reads only.
Collector-specific variables are tracked in the repository environment baseline;
the opt-in application identity/auth settings are documented in Compose env templates.

Optional managed-service reads use `ONYX_TELEMETRY_AWS_RESOURCES_JSON` and `AWS_REGION`.
The isolated collector reads at most 32 resource targets in one bounded CloudWatch request.
Targets specify `kind` (`rds`, `elasticache`, or `opensearch`), `resource_id`, and reviewed
`cpu_limit_cores`, `memory_limit_bytes`, or `disk_limit_bytes` for the same instance scope.
Redis requires `node_id`; OpenSearch requires `node_id` and `account_id`.
Raw identifiers remain local. The collector emits fixed service roles and keyed IDs.
Missing metrics or allocations stay unavailable. RDS memory use is derived from freeable memory;
Redis memory describes engine capacity, and OpenSearch memory describes operating-system utilization.
In Helm, enable `collector.awsResources` on one collector and put JSON in the existing Secret.
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
    public.sync_record,
    public.doc_permission_sync_attempt,
    public.external_group_permission_sync_attempt,
    public.hierarchy_fetch_attempt,
    public.port_attempt
TO onyx_fleet_reader;
ALTER ROLE onyx_fleet_reader SET default_transaction_read_only = on;
ALTER ROLE onyx_fleet_reader SET statement_timeout = '1500ms';
ALTER ROLE onyx_fleet_reader SET lock_timeout = '100ms';
ALTER ROLE onyx_fleet_reader CONNECTION LIMIT 2;
```

Do not grant access to credentials, users, document contents, file storage, or chat message tables.
Avoid `GRANT SELECT ON ALL TABLES` and blanket default privileges.
Provision these grants for new tenant schemas through the existing tenant provisioning process.
The two-connection role limit assumes one collector uses the role. For multiple
collectors, use separate roles or raise this limit to twice the configured collector count.

## Verification

Development builds report `dev`. Release builds use the existing `ONYX_VERSION`.
Set optional `ONYX_BUILD_SHA` to the build's lowercase hex Git commit (7–40 characters)
to identify the source revision. Invalid values are omitted; telemetry does not invoke Git.
Heartbeat delivery counters separate recent loss from cumulative drops, local validation
failures, and server rejections. Queues remain bounded and lossy across process termination.
Connector jobs include the integration ID when their source table identifies it. Unknown
work totals stay unavailable. Long-running jobs without a progress timestamp raise a
coverage warning; a stale reported progress timestamp raises a stall issue.

Unit tests cover strict privacy validation, fault isolation, lock contention, bounded queues,
partial HTTP acknowledgments, stable retry IDs, first-answer timing, and OpenSearch item acknowledgments.
They also verify Kubernetes resource denominators and content exclusion.

Run source tests against a migrated test database:

```sh
ONYX_TELEMETRY_TEST_DB="$TEST_SOURCE_DATABASE_URL" uv run pytest backend/tests/external_dependency_unit/telemetry/test_fleet_collector.py
```

The tests create and remove an isolated schema. They check 250 connector pages,
terminal failures, permission/group syncs, source read-only enforcement, and schema validation.
