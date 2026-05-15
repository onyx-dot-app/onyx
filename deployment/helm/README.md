# Recent chart changes (0.5.0)

If you are upgrading from an earlier 0.4.x release, note:

* **Redis** — the chart now bundles the `redis-operator` subchart alongside the
  `redis` subchart. The operator installs the CRD that the Redis CR binds to,
  so `helm install` works on a clean cluster without a separate CRD step.
* **PostgreSQL** — a CloudNativePG `Cluster` CR is now rendered from
  `templates/postgres-cluster.yaml`, so `helm install` provisions postgres
  out of the box. The Cluster is named `<release>-pg` (service:
  `<release>-pg-rw`). Set `postgresql.enabled: false` and override
  `configMap.POSTGRES_HOST` if you use an external database (RDS, etc.).
* **REDIS_HOST** — the configmap no longer appends `-master` to the redis
  service name. If you previously overrode `REDIS_HOST` or had clients that
  hard-coded the `-master` suffix, update them to point at the
  redis-operator standalone service.
* **CNPG CRDs** — copied into `crds/cnpg-crds.yaml` so Helm pre-installs
  them before templates. The subchart's own CRD template is disabled
  (`postgresql.crds.create: false`). Run `scripts/check-cnpg-crds.sh` after
  bumping the CNPG subchart version to verify the copy is in sync.
* **Pre-delete hook** — a cleanup Job (`templates/pre-delete-cleanup.yaml`)
  deletes operator-managed CRs before `helm uninstall` tears down the
  operators, ensuring finalizers are processed and namespace cleanup
  completes promptly.

# Dependency updates (when subchart versions are bumped)
* If updating subcharts, you need to run this before committing!
* cd charts/onyx
* helm dependency update .

# Prerequisites

## Redis operator (automatic with bundled Redis)

When `redis.enabled: true` (the chart default), the chart bundles and automatically
installs the `redis-operator` subchart alongside the `redis` subchart. The operator
provides the CRD that the Redis CR binds to, so `helm install` works on a clean
cluster without manual preparation.

**No separate pre-install step is needed** — the chart handles the redis-operator
CRD and controller automatically as part of `helm install onyx onyx/onyx`.

If you don't want the bundled Redis (recommended for production environments using
managed Redis like AWS ElastiCache), see [Using an external Redis](#using-an-external-redis)
below and set `redis.enabled: false` to skip the operator entirely.

## Using an external Redis

To point Onyx at an externally-managed Redis (e.g. AWS ElastiCache) and skip
the bundled Redis + operator entirely:

```yaml
redis:
  enabled: false

configMap:
  # Override the chart-computed REDIS_HOST. Use the cluster/primary endpoint
  # from your managed Redis. Avoid underscores — they are invalid in K8s DNS
  # labels and look identical to a hung service.
  REDIS_HOST: "<elasticache-primary-endpoint>"
  REDIS_PORT: "6379"
  REDIS_SSL: "true"   # set to "true" if in-transit encryption is enabled

auth:
  redis:
    enabled: true
    # Pre-create a Secret in the release namespace holding the Redis password
    # under the key `redis_password`.
    existingSecret: "elasticache-auth-secret"
    secretKeys:
      REDIS_PASSWORD: redis_password
```

# Values that come from docker-compose (do not copy them)

The Onyx docker-compose stack uses service-name hostnames like `api_server`,
`inference_model_server`, and `cache`. Those names contain underscores, which
are **invalid in Kubernetes DNS labels** — DNS lookups for them will fail and
the symptom is often a blank login page or `TypeError: fetch failed` in web
pod logs.

The chart computes correct K8s service hostnames for you. If you are
adapting an `.env` file from docker-compose, **remove** these keys from your
Helm `configMap:` and let the chart fill them in:

| Key | Don't set to (docker-compose) | Chart-computed default |
| --- | --- | --- |
| `REDIS_HOST` | `cache` | `redis.redisStandalone.name | default <release>` |
| `INTERNAL_URL` | `http://api_server:8080` | `http://<release>-api-service:8080` |
| `API_SERVER_HOST` | `api_server` | computed |
| `MODEL_SERVER_HOST` | `inference_model_server` | `<release>-inference-model-service` |
| `INDEXING_MODEL_SERVER_HOST` | `indexing_model_server` | `<release>-indexing-model-service` |

Other docker-compose-style values you should set deliberately:

* `DOMAIN` should be your public hostname (e.g. `onyx.example.com`), not
  `localhost`. It affects cookies and CORS.
* `WEB_DOMAIN` should be the full origin (e.g. `https://onyx.example.com`).
  Watch for typos like `hhttps://...`; they silently break email links and
  OAuth redirects.

# Local testing

> This section covers chart-maintainer testing; for the Onyx Craft local-kind developer workflow, see [docs/dev/local-kubernetes.md](/docs/dev/local-kubernetes.md).

## One time setup
* brew install kind
* Ensure you have no config at ~/.kube/config
* kind create cluster
* mv ~/.kube/config ~/.kube/kind-config

## Automated install and test with ct
* export KUBECONFIG=~/.kube/kind-config
* kubectl config use-context kind-kind
* from source root run the following. This does a very basic test against the web server
  * ct install --all --helm-extra-set-args="--set=nginx.enabled=false" --debug --config ct.yaml

## Output template to file and inspect
* cd charts/onyx
* helm template test-output . --set auth.opensearch.values.opensearch_admin_password='StrongPassword123!' > test-output.yaml

## Test the entire cluster manually
* cd charts/onyx
* helm install onyx . -n onyx --set postgresql.primary.persistence.enabled=false --set auth.opensearch.values.opensearch_admin_password='StrongPassword123!'
  * the postgres flag is to keep the storage ephemeral for testing. You probably don't want to set that in prod.
  * the OpenSearch admin password must be set on first install unless you are supplying `auth.opensearch.existingSecret`.
  * no flag for ephemeral vespa storage yet, might be good for testing
* kubectl -n onyx port-forward service/onyx-nginx 8080:80
  * this will forward the local port 8080 to the installed chart for you to run tests, etc.
* When you are finished
  * helm uninstall onyx -n onyx
  * Vespa leaves behind a PVC. Delete it if you are completely done.
    * k -n onyx get pvc
    * k -n onyx delete pvc vespa-storage-da-vespa-0
  * If you didn't disable Postgres persistence earlier, you may want to delete that PVC too.

## Run as non-root user
By default, some onyx containers run as root. If you'd like to explicitly run the onyx containers as a non-root user, update the values.yaml file for the following components:
  * `celery_shared`, `api`, `webserver`, `indexCapability`, `inferenceCapability`
    ```yaml
    securityContext:
      runAsNonRoot: true
      runAsUser: 1001
    ```
  * `vespa`
    ```yaml
    podSecurityContext:
      fsGroup: 1000
    securityContext:
      privileged: false
      runAsUser: 1000
    ```

## Resourcing
In the helm charts, we have resource suggestions for all Onyx-owned components. 
These are simply initial suggestions, and may need to be tuned for your specific use case.

Please talk to us in Slack if you have any questions!

## Autoscaling options
The chart renders Kubernetes HorizontalPodAutoscalers by default. To keep this behavior, leave
`autoscaling.engine` as `hpa` and adjust the per-component `autoscaling.*` values as needed.

If you would like to use KEDA ScaledObjects instead:

1. Install and manage the KEDA operator in your cluster yourself (for example via the official KEDA Helm chart). KEDA is no longer packaged as a dependency of the Onyx chart.
2. Set `autoscaling.engine: keda` in your `values.yaml` and enable autoscaling for the components you want to scale.

When `autoscaling.engine` is set to `keda`, the chart will render the existing ScaledObject templates; otherwise HPAs will be rendered.
