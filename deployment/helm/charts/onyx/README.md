## Chat engine

`chatEngine: pi` is the default. Use `chatEngine: legacy` for the original in-process LiteLLM loop.
The chart passes the engine to API and background services. Legacy mode omits Pi workers and queue resources.
Drain active chats before changing engines. Restart services together; active runs cannot move between engines.

## Pi worker scaling

The `agent` Deployment consumes chat jobs from persistent Redis. API servers execute tools.
The default is two workers with 64 active runs per worker. These limits need workload testing.
`agent.runTimeoutSeconds` sets the API and worker run budget, including queue wait.
The supported range is 1–1800 seconds. Runs cannot exceed 30 minutes.

Enable `agent.autoscaling.enabled` to create a KEDA ScaledObject. Install KEDA and configure Prometheus scraping first.
Set `agent.autoscaling.prometheusAddress` and `agent.autoscaling.query`. For example, with pod scrape labels:

```yaml
agent:
  autoscaling:
    enabled: true
    prometheusAddress: http://prometheus.monitoring:9090
    query: 'max(onyx_agent_outstanding_runs{namespace="onyx",pod=~"onyx-agent-.*"})'
```

Adapt labels to the scrape configuration. Select only this release's workers.
Each worker reports the same global queue count. Use `max`, not `sum`.
The count includes active and runnable queued jobs. The target is 40 runs per replica.
KEDA owns the HPA; do not add another HPA for this Deployment.
Scale-down waits five minutes and removes at most one replica per minute.

Workers drain active runs on shutdown. The default termination grace period is 1830 seconds.
Keep that period longer than `agent.drainTimeoutSeconds` plus 20 seconds for cleanup. Forced termination can interrupt runs.
The cluster needs enough resources for replacement pods during draining.

The bundled `agent.redis` StatefulSet uses a persistent volume, AOF, and `noeviction`.
It is a single Redis instance. Use managed Redis for high availability across failures.
Set `agent.redis.enabled=false` and `agent.redis.existingSecret` to a Secret containing a Redis URL under `url`.
Use a distinct nonpersistent Redis instance for transient chat state, including incognito payloads.
By default, state uses the application's Redis. Override with `agent.stateRedis.existingSecret` if needed.
Changing the application's Redis persistence settings also affects incognito chat state.
