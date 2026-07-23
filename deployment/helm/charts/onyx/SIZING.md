# Sizing the Onyx chart

The chart's default resources are calibrated for a mid-size deployment
(roughly 200–1,000 users, up to ~2M documents) with everything at one
replica. This guide covers what to change as your deployment grows or
shrinks. Copy the snippets you need into **your own values file** — sizing
depends on which components you run in-cluster versus managed (an in-cluster
OpenSearch pod next to an RDS Postgres is a perfectly normal mix), so there
is no one-size preset.

Rough tiers, matching the `size` input of the terraform module in
`deployment/terraform/modules/aws` (see its README):

| Tier | Users | Documents | Node pairing (terraform) |
|---|---|---|---|
| small | up to ~200 | < ~500k | 1× 8 vCPU / 32 GiB (m7i.2xlarge)¹ |
| medium | ~200–1,000 | ~0.5–2M | m7i.4xlarge ×1–5 |
| large | 1,000+ | multi-million | m7i.4xlarge ×2–8 + dedicated index node |

¹ Only with Postgres, Redis, and object storage external (RDS / ElastiCache
/ S3). Keeping those in-cluster too needs a second node.

## Principles (learned from production fleets)

- **Requests are for scheduling, limits are for bursts.** Steady-state usage
  is a fraction of the defaults' requests; what breaks deployments is almost
  always a *limit* (CPU throttling, OOM), not a request.
- **Scale the api-server out, not up.** Use the HPA with a CPU target only —
  idle api-server RSS (~1.1Gi) sits near the memory request, so a memory
  target pins the HPA at max.
- **OpenSearch memory pressure is off-heap** (k-NN native memory + Lucene
  page cache). Raise the container memory as the index grows, but keep the
  Java heap at ~4g until you have heap-usage evidence — do not scale heap
  proportionally.
- **A pegged indexing model server is not just slow.** An embedder stuck at
  its CPU limit for hours during a large re-index can starve docprocessing
  heartbeats and trip the indexing stall watchdog. Raise the indexing limit
  (and add a replica) before a planned bulk re-index.

## Small — trim for a single node

```yaml
webserver:
  replicaCount: 2  # keeps rolling deploys seamless

# Embedding traffic is light and bursty at this scale.
inferenceCapability:
  resources:
    requests: {cpu: 500m, memory: 3Gi}
    limits: {cpu: 3000m, memory: 10Gi}
indexCapability:
  resources:
    requests: {cpu: 500m, memory: 3Gi}
    limits: {cpu: 3000m, memory: 6Gi}

# Coordination singletons measure single-digit millicores in production.
celery_beat:
  resources:
    requests: {cpu: 250m, memory: 512Mi}
    limits: {cpu: 1000m, memory: 1Gi}
celery_worker_monitoring:
  resources:
    requests: {cpu: 250m, memory: 512Mi}
    limits: {cpu: 1000m, memory: 4Gi}
celery_worker_primary:
  resources:
    requests: {cpu: 250m, memory: 2Gi}
    limits: {cpu: 1000m, memory: 4Gi}

# Craft build-loop worker; set back to 1 if you use Craft/sandbox features.
celery_worker_scheduled_tasks:
  replicaCount: 0

# If your document index is in-cluster (opensearch.enabled: true):
opensearch:
  resources:
    requests: {cpu: 1000m, memory: 4Gi}
    limits: {cpu: 2000m, memory: 8Gi}
```

With an external data plane this renders ~6.9 vCPU / ~22 GiB of requests —
it fits one 8 vCPU / 32 GiB node.

## Medium — the shape production deployments converge on

```yaml
webserver:
  replicaCount: 3

api:
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 6
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: null  # see Principles

# 2 replicas so concurrent connector backfills don't starve each other and
# one bad fetch doesn't take out all ingestion.
celery_worker_docfetching:
  replicaCount: 2

# If your document index is in-cluster — working sets at this scale run
# 5–6Gi+ (off-heap; keep heap at the default ~4g):
opensearch:
  resources:
    requests: {cpu: 2000m, memory: 6Gi}
    limits: {cpu: 4000m, memory: 12Gi}
  persistence:
    size: 128Gi  # existing PVCs must be expanded manually
```

## Large — org-wide, sustained re-indexes

```yaml
webserver:
  replicaCount: 3

api:
  # Generous CPU limit: bursty agent work (deep research, code interpreter)
  # exhausting the CFS quota stalls /health and causes liveness kills.
  resources:
    requests: {cpu: 1000m, memory: 2Gi}
    limits: {cpu: 4000m, memory: 8Gi}
  autoscaling:
    enabled: true
    minReplicas: 4
    maxReplicas: 12
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: null

# Two embedders with high CPU limits — see Principles on pegged embedders.
indexCapability:
  replicaCount: 2
  resources:
    requests: {cpu: 4000m, memory: 3Gi}
    limits: {cpu: 12000m, memory: 6Gi}

celery_worker_docfetching:
  replicaCount: 2
celery_worker_docprocessing:
  replicaCount: 2
  resources:
    requests: {cpu: 500m, memory: 2Gi}
    limits: {cpu: 1000m, memory: 18Gi}

# Metadata-sync throughput: one light worker drains ~800 tasks/min, which
# means multi-day backlogs after resyncs of multi-million-doc document sets.
celery_worker_light:
  replicaCount: 3

celery_worker_user_file_processing:
  replicaCount: 2
  resources:
    requests: {cpu: 500m, memory: 512Mi}
    limits: {cpu: 2000m, memory: 4Gi}

# If your document index is in-cluster:
opensearch:
  resources:
    requests: {cpu: 2000m, memory: 12Gi}
    limits: {cpu: 4000m, memory: 16Gi}
  opensearchJavaOpts: "-Xmx6g -Xms6g"
  persistence:
    size: 512Gi
  # Let the index land on the dedicated document-index node group created by
  # the terraform module (tainted vespa-dedicated=true on new clusters —
  # without this toleration that node sits idle).
  tolerations:
    - key: vespa-dedicated
      operator: Equal
      value: "true"
      effect: NoSchedule
```

## Managed document index instead?

If you use a managed OpenSearch domain (`opensearch.enabled: false` +
`OPENSEARCH_HOST` in the configMap), skip every `opensearch:` block above and
size the domain in terraform instead. In that case the terraform module's
dedicated index node group has nothing to run — shrink
`vespa_node_instance_types` to a small instance.
