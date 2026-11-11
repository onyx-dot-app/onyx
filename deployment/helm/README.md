# Installing the chart

## Helm repository (default)

```bash
helm repo add onyx https://onyx-dot-app.github.io/onyx
helm repo update
helm install onyx onyx/onyx -n onyx --create-namespace
```

Chart tarballs are attached to GitHub releases named `helm/onyx-<version>`, and
`index.yaml` on the `gh-pages` branch points at them. This is an implementation
detail: the repository URL above does not change and `helm repo add`,
`helm search repo` and `helm upgrade` all work as before.

## OCI registry (alternative)

The same chart is published to GHCR:

```bash
helm install onyx oci://ghcr.io/onyx-dot-app/charts/onyx \
  --version 0.8.16 -n onyx --create-namespace
```

`helm repo add` does not accept `oci://` URLs, so an OCI install needs an
explicit `--version`. There is no `helm repo update` or `helm search repo` for
OCI and no helm command that lists the available versions. Read them from the
`helm/onyx-<version>` [releases](https://github.com/onyx-dot-app/onyx/releases)
or from the Helm repository index:

```bash
helm search repo onyx/onyx --versions   # needs `helm repo add` from above
```

To inspect one version before installing it:

```bash
helm show chart oci://ghcr.io/onyx-dot-app/charts/onyx --version 0.8.16
```

Both channels ship identical bytes from the same build. Use the Helm repository
unless you specifically need OCI.

# Recent chart changes (0.5.0)

If you are upgrading from an earlier 0.4.x release, **read [MIGRATION.md](./MIGRATION.md) first.** The 0.5.0 release dropped the bundled Vespa subchart. Onyx no longer uses Vespa.

Other 0.5.0 changes:

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
  deletes this release's CNPG Cluster and Redis CRs, by name, before
  `helm uninstall` tears down the operators. This makes sure finalizers are
  processed and namespace cleanup completes promptly. Set
  `postgresql.cluster.retainOnUninstall: true` to keep the CNPG Cluster and
  its PVCs instead. The operator is still removed, so the kept Cluster has no
  controller: reinstall with the same release name to adopt it, or delete it
  and clear its finalizers (see the comment in `values.yaml`).

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

## Onyx Craft with Kubernetes sandboxes

When `configMap.ENABLE_CRAFT="true"`, the target cluster must run Kubernetes
`>= 1.33`. Craft Helm deployments provision Kubernetes sandbox pods; Docker
is not a Helm deployment backend for Craft and `configMap.SANDBOX_BACKEND` is
not a bypass for this requirement.

Craft sandbox pods use native restartable init sidecar containers:
`sandbox-init` runs and completes first, `sidecar` starts next as an
`initContainers` entry with `restartPolicy: Always`, and the main `sandbox` app
container starts after the sidecar's startup restore gate is ready.

The chart fails during render/install on older clusters so the incompatibility
is caught before sandbox provisioning. This guard does not apply to non-Craft
installs.

### Sandbox runtime and network enforcement

The default sandbox uses the cluster's default runtime and installs iptables
rules before any workload starts. You can select a cluster-provided RuntimeClass:

```yaml
sandboxPod:
  runtimeClassName: your-runtime
  netAdminLockdown: true
```

The cluster administrator must configure the runtime and compatible nodes.
Runtime selection does not replace network restrictions. Test the chosen runtime
with Craft. The current sandbox image uses nft-based iptables. With gVisor
release-20261005.0 in its default configuration, firewall bootstrap fails with
`Protocol not supported`. That tested configuration needs external network
enforcement with lockdown disabled. Other firewall backends or runtime settings
need separate validation.
These settings apply to newly created sandbox pods after a Helm upgrade.
The image prepuller uses the same RuntimeClass to follow its scheduling constraints.

For clusters that prohibit `NET_ADMIN`, set `sandboxPod.netAdminLockdown: false`
only when the cluster enforces equivalent network restrictions from pod creation.
This removes `NET_ADMIN` from `sandbox-init` and skips firewall commands and
verification. CA installation still runs as root. This setting alone does not
make the pod compatible with policies that prohibit root init containers.
Use a sandbox image built with this option; older images still run iptables.

In this mode, the chart's policies allow only the proxy endpoint. A separate DNS
policy excludes pods created with lockdown disabled, including after Helm upgrades.
This also applies to `craft.dnsExtraCIDRs`. The backend supplies the proxy address
through pod `hostAliases`. Proxy environment variables, CA
trust, destination checks, and approval handling remain active.

The operator must use a CNI that enforces NetworkPolicy before workload startup.
Other policies must not grant broader access. Verify IPv4 and IPv6 restrictions,
including internal services, node addresses, and cloud metadata. Standard
NetworkPolicy has node-traffic exceptions; additional cluster controls may be
needed. A rendered policy cannot prove enforcement. Test direct connections with
proxy variables removed, and confirm approved requests still work through the
proxy. Do not disable lockdown solely because a sandboxed runtime is selected.

The proxy also needs cluster access to the Kubernetes API, DNS, and Onyx services.
Some CNIs exclude cluster destinations from IP-range rules; see
[Cilium CIDR policies](https://docs.cilium.io/en/latest/security/policy/layer3/#cidr-based).
Configure explicit proxy access for these destinations when required by the CNI.
Keep those rules scoped to the proxy pods.

Docker deployments retain mandatory iptables enforcement. The bootstrap rejects
disabling lockdown in Docker entrypoint mode.

### Check your nodes for Craft Firecracker

Craft will run sandboxes as Firecracker microVMs on sandbox nodes. Before you
use that runtime, run the preflight check. It does not need `ENABLE_CRAFT`.

```yaml
craft:
  firecrackerPreflight:
    enabled: true
```

The chart then adds a DaemonSet, `<release>-craft-fc-preflight`, in the
release namespace. It puts one pod on each node that matches
`sandboxPod.nodeSelector` and `sandboxPod.tolerations`. It does not use
`sandboxPod.runtimeClassName`, because gVisor and Kata hide `/dev/kvm`.

Each pod runs the checks once at start, then stays idle. Read the results:

```bash
kubectl logs -n <release-namespace> --prefix --tail=-1 \
  -l app.kubernetes.io/component=craft-fc-preflight,app.kubernetes.io/instance=<release>
```

The first line names the node. Each check line starts with `PASS`, `WARN` or
`FAIL`. The last line of each pod is `RESULT: PASS (<N> warnings)` or
`RESULT: FAIL (<N> failed, <M> warnings)`. A failed check does not make the
pod unready, so `helm upgrade --wait` does not stop.

| Check | Pass condition | Fix if it fails |
|---|---|---|
| `kvm` | `/dev/kvm` exists and opens read-write | Use a metal instance, or enable nested virtualization on the node pool |
| `cpu-vendor` | `GenuineIntel` | Use an Intel instance type |
| `cpu-vmx` | The `vmx` CPU flag is present | Enable nested virtualization |
| `cgroup` | cgroup v2 | Use a node image with the unified cgroup hierarchy |
| `kernel` | 5.10, 6.1 or 6.18 (WARN only) | Use AL2023 with kernel 6.18 |
| `max-map-count` | `vm.max_map_count` >= 1048576 | Set the sysctl on the node pool |
| `filesystem` | `scratchHostPath` is writable, and is XFS with reflink (WARN if not XFS) | Free space or fix permissions; on ext4, the host agent will use an XFS loop file |
| `free-disk` | At least `minFreeDiskGi` free (WARN only) | Use a larger root disk |

The filesystem and disk checks run in `scratchHostPath`
(default `/var/lib/onyx-craft-fc-preflight`). The chart creates this directory
on the node. Set it to a directory on the filesystem that will hold sandbox
data.

The pod is privileged by default. A non-privileged container cannot open
`/dev/kvm`, because the container device cgroup blocks it. If the cluster runs
a KVM device plugin, set its resource name to run the pod without privilege:

```yaml
craft:
  firecrackerPreflight:
    enabled: true
    kvmDeviceResource: devices.kubevirt.io/kvm
```

The pod uses the sandbox image by default. Set `craft.firecrackerPreflight.image`
to use a different image. The image must have a POSIX shell, awk, grep and GNU coreutils (`cp --reflink`,
`stat -f`, `mktemp`).
Remove the DaemonSet after the check: set `enabled: false` and upgrade.

### Craft Firecracker runtime (not usable yet)

`craft.sandboxRuntime` selects how Craft sandboxes run: `pod` (default) or
`firecracker`. It mirrors the Terraform `craft_sandbox_runtime` of the sandbox
node pool. Keep `pod`: the backend Firecracker sandbox manager is not released.

With `firecracker`, the chart:

- sets `SANDBOX_RUNTIME=firecracker` for the backend and sandbox-proxy;
- deploys the host agent (`onyxdotapp/craft-fc-host-agent`), a privileged
  DaemonSet with `hostPID` and `/dev/kvm`, on the sandbox nodes that have the
  label `onyx.app/kvm=true`;
- puts the agent in its own namespace (`craft.hostAgent.namespace`) with Pod
  Security `privileged`;
- adds a headless Service for the agent port (7443);
- lets only the agent clients (api_server, heavy and scheduled-tasks workers)
  reach the agent port, and lets the agent pods reach the sandbox-proxy port;
- gives the agent `POD_IP`, so the agent registers `<pod IP>:7443` with its
  node key (`craft.hostAgent.advertiseAddress` overrides it).

The agent needs a TLS Secret in the agent namespace. It holds the agent
certificate (`tls.crt`, `tls.key`) and the CA of the api_server client
certificates (`ca.crt`). The chart does not make certificates. Until the Secret
exists, the agent pods stay in `ContainerCreating`.

The agent clients need a second Secret, in the release namespace
(`craft.hostAgent.client.existingSecret`). It holds the client certificate
(`tls.crt`, `tls.key`, signed by the CA in the agent `ca.crt`) and the CA of the
agent certificates (`ca.crt`). The chart mounts it in the api_server, heavy and
scheduled-tasks pods and sets `SANDBOX_FC_AGENT_CLIENT_CERT_PATH`,
`SANDBOX_FC_AGENT_CLIENT_KEY_PATH` and `SANDBOX_FC_AGENT_CA_PATH`. The clients
dial agent pod IPs. If the agent certificates do not carry the pod IPs, set
`craft.hostAgent.client.tlsServerName` (`SANDBOX_FC_AGENT_TLS_SERVER_NAME`) to
a DNS name in the agent certificate. To accept only some client certificates,
set `craft.hostAgent.clientAllowedSans`.

```yaml
craft:
  sandboxRuntime: firecracker
  hostAgent:
    image:
      tag: "<host agent version>"
    tls:
      existingSecret: craft-fc-host-agent-tls
    client:
      existingSecret: craft-fc-agent-client-tls
      tlsServerName: craft-fc-host-agent
auth:
  sandboxNodeRegistration:
    enabled: true
    values:
      sandbox_node_registration_secret: "<random value>"
```

The chart copies `sandbox_node_registration_secret` into the agent namespace.
If you change `auth.sandboxNodeRegistration.secretKeys`, the copy uses the same
key. If `auth.sandboxNodeRegistration` uses `existingSecret`, create the same
Secret (with the same key) in the agent namespace too and set
`craft.hostAgent.registrationExistingSecret`.

For a private agent image, create the pull Secret in the agent namespace and
set `craft.hostAgent.imagePullSecrets`. The release `imagePullSecrets` are not
used there, because Secrets are namespaced.
To manage the agent namespace yourself, set `craft.hostAgent.createNamespace:
false` and give the namespace the label
`pod-security.kubernetes.io/enforce: privileged`.
The agent data dir (`craft.hostAgent.dataDir`, default `/var/lib/craft-fc`)
must be on XFS with reflink. The preflight above checks
`craft.firecrackerPreflight.scratchHostPath`, not the data dir. Set
`scratchHostPath` to the same path as `dataDir` for the check, or check the
data dir on a node (`stat -f -c %T <dataDir>` must print `xfs`, and
`xfs_info` must show `reflink=1`). The agent also checks reflink support at
start-up and does not start without it.

To scrape the agent metrics, set `craft.hostAgent.metrics.enabled: true`
(port `craft.hostAgent.metrics.port`, default 9464). With
`monitoring.serviceMonitors.enabled: true`, the chart also makes a
ServiceMonitor in the agent namespace. Auth follows the API server `/metrics`:
with `auth.metricsAuth.enabled`, the agent requires the same bearer token and
the ServiceMonitor sends it. The chart copies `auth.metricsAuth.values` into
the agent namespace, because Secrets are namespaced. If `auth.metricsAuth`
uses `existingSecret`, create a Secret with the same key in the agent
namespace and set `craft.hostAgent.metrics.authExistingSecret`. With
`configMap.DISABLE_METRICS_AUTH: "true"` the agent has no auth. With neither,
every scrape gets 401. The NetworkPolicy lets only Prometheus Operator pods
(`app.kubernetes.io/name: prometheus`) in the release namespace reach the
port. If Prometheus runs in another namespace, set
`craft.hostAgent.metrics.networkPolicyFrom`. The agent writes each VM's serial console and Firecracker log to its
stdout as JSON lines (`kind=guest_log`), and an audit line for every API call
to stderr (`kind=audit`), so the cluster log pipeline collects both.

With the agent metrics on, `monitoring.grafana.dashboards.enabled: true` also
deploys the "Onyx Craft Firecracker Host Agent" dashboard, and
`monitoring.prometheusRules.enabled: true` deploys its alert rules (a
PrometheusRule in the release namespace; set `monitoring.prometheusRules.labels`
to match your Prometheus `ruleSelector`). The thresholds in
`craft.hostAgent.alerts` are proposed defaults. `CraftFcHostAgentPodsMissing`
needs kube-state-metrics. The dashboard and the rules need the agent series:
set `monitoring.serviceMonitors.enabled: true` (with
`monitoring.serviceMonitors.labels` that match your Prometheus
`serviceMonitorSelector`), unless another scrape configuration collects the
agent metrics. Runbooks: `microvm/RUNBOOKS.md`.

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

# Enables verified TLS and mounts the Redis server CA into all Redis clients,
# including the Craft sandbox proxy.
redisTls:
  enabled: true
  caConfigMapName: "elasticache-ca"
  caKey: ca.crt

auth:
  redis:
    enabled: true
    # Pre-create a Secret in the release namespace holding the Redis password
    # under the key `redis_password`.
    existingSecret: "elasticache-auth-secret"
    secretKeys:
      REDIS_PASSWORD: redis_password
```

## Sourcing secrets from an external secret manager (ESO)

The chart can render an `ExternalSecret` CR that has [External Secrets
Operator](https://external-secrets.io/) materialize a single Kubernetes Secret
from an upstream provider (AWS Secrets Manager, GCP Secret Manager, Vault,
etc.). All `auth.*` sections then read their per-section keys from that
materialized Secret, and any loose env-var secrets are projected into pods
via `envFrom`.

**Prerequisite:** the chart does *not* install ESO. Install it separately and
create a `SecretStore` or `ClusterSecretStore` (e.g. `aws-secrets-manager`)
before enabling `externalSecret`. See https://external-secrets.io/ for setup.

The upstream secret should be a JSON object whose top-level keys map 1:1 to
the keys the chart expects in the materialized Secret (the union of every
`auth.<section>.secretKeys` value plus any loose env-var names you project via
`extraEnvFromSecret`).

```yaml
externalSecret:
  enabled: true
  # Identifier of the upstream secret (e.g. AWS Secrets Manager secret name).
  refPath: "onyx/<customer>/app-secrets"
  # Name of the materialized k8s Secret. Point auth.*.existingSecret here.
  secretName: onyx-app-secrets
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  refreshInterval: 1h

# Inject every key from onyx-app-secrets as an env var on backend pods.
# Use for secrets that today live as plaintext in `configMap:` blocks.
extraEnvFromSecret: onyx-app-secrets

auth:
  postgresql:
    existingSecret: onyx-app-secrets
    secretKeys:
      POSTGRES_USER: postgres_user
      POSTGRES_PASSWORD: postgres_password
  redis:
    existingSecret: onyx-app-secrets
    secretKeys:
      REDIS_PASSWORD: redis_password
  # ...repeat for any other auth section that should read from the shared Secret.
```

When `externalSecret.enabled: false` (the default) the chart renders exactly
as before — no `ExternalSecret` CR is created and `envFrom` is unchanged.

### First-install reconciliation window

The Helm release renders both the `ExternalSecret` CR and the Deployments that
reference the materialized Secret in the same apply. ESO reconciles the CR
asynchronously, typically within a few seconds. During that brief window,
backend pods will be in `CreateContainerConfigError` because their
`envFrom: secretRef` references a Secret that does not yet exist. The kubelet
retries pod creation automatically; once ESO materializes the Secret, pods
transition to `Running` without manual intervention.

We intentionally leave the `secretRef` non-optional. Marking it optional would
allow pods to boot with empty env vars and fail later in a way that is harder
to diagnose; the brief `CreateContainerConfigError` is the clearer failure
mode if anything is misconfigured (wrong SM path, missing IRSA permissions,
missing keys in the upstream blob).

If you need pods to be `Ready` before traffic is routed, rely on the existing
readiness probes — they will not pass until the env vars are present.

### Model-server pods

`indexing-model-deployment` and `inference-model-deployment` deliberately do
**not** consume `extraEnvFromSecret`. Model servers only need model-config
env vars (already in the chart's `configMap`), so injecting application-level
secrets like `POSTGRES_PASSWORD` would needlessly widen their secret-exposure
surface.

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

> This section covers chart-maintainer testing; for the Onyx Craft local-kind developer workflow, see [dev/README.md](dev/README.md).

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
* Craft Kubernetes sandbox version guard check:
  * expect failure:
    `helm template test-output . -f values-ci.yaml --kube-version 1.32.0 --show-only templates/craft-kubernetes-version-check.yaml`
  * expect success:
    `helm template test-output . -f values-ci.yaml --kube-version 1.33.0 --show-only templates/craft-kubernetes-version-check.yaml`

## Test the entire cluster manually
* cd charts/onyx
* helm install onyx . -n onyx --set postgresql.primary.persistence.enabled=false --set auth.opensearch.values.opensearch_admin_password='StrongPassword123!'
  * the postgres flag is to keep the storage ephemeral for testing. You probably don't want to set that in prod.
  * the OpenSearch admin password must be set on first install unless you are supplying `auth.opensearch.existingSecret`.
* kubectl -n onyx port-forward service/onyx-nginx 8080:80
  * this will forward the local port 8080 to the installed chart for you to run tests, etc.
* When you are finished
  * helm uninstall onyx -n onyx
  * If you didn't disable Postgres persistence earlier, you may want to delete that PVC too.

## Run as non-root user
By default, some onyx containers run as root. If you'd like to explicitly run the onyx containers as a non-root user, update the values.yaml file for the following components:
  * `celery_shared`, `api`, `webserver`, `indexCapability`, `inferenceCapability`
    ```yaml
    securityContext:
      runAsNonRoot: true
      runAsUser: 1001
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
