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

# Local testing

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
