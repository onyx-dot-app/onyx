# Craft Firecracker host agent runbooks

One section for each alert in
`deployment/helm/charts/onyx/templates/craft-fc-host-agent-prometheusrule.yaml`, then the
operator procedures. The metrics are in `README.md` (Metrics, guest logs and audit). The
dashboard is "Onyx Craft Firecracker Host Agent" (`deployment/helm/charts/onyx/dashboards/craft-fc-host-agent.json`).

The examples use the default names. Change them to match your install:

```bash
CTX=<kube context>                # always pass --context
NS=onyx-sandbox-runtime           # craft.hostAgent.namespace
REL=onyx                          # release namespace
DS=onyx-craft-fc-host-agent       # <release fullname>-craft-fc-host-agent
K="--context $CTX"
pod_on() { kubectl $K -n $NS get pod -l app.kubernetes.io/component=craft-fc-host-agent \
  --field-selector spec.nodeName="$1" -o name; }
```

## Call the agent API

The agent serves gRPC with mTLS on port 7443 (`craft.hostAgent.listenPort`). It has no gRPC
reflection, so give `grpcurl` the proto file. Use the client certificate that the api_server uses
(`craft.hostAgent.client.existingSecret`, in the release namespace).

```bash
SECRET=<craft.hostAgent.client.existingSecret>
SERVER_NAME=<craft.hostAgent.client.tlsServerName>
D=$(mktemp -d)
for k in tls.crt tls.key ca.crt; do
  kubectl $K -n $REL get secret "$SECRET" -o jsonpath="{.data.${k//./\\.}}" | base64 -d > "$D/$k"
done
kubectl $K -n $NS port-forward "$(pod_on <node>)" 7443:7443 &
agent() {  # agent <Method> [JSON body]
  local body=${2:-'{}'}
  grpcurl -cert "$D/tls.crt" -key "$D/tls.key" -cacert "$D/ca.crt" -authority "$SERVER_NAME" \
    -import-path microvm/proto -proto hostagent/v1/hostagent.proto \
    -d "$body" localhost:7443 "craft.hostagent.v1.HostAgent/$1"
}
agent NodeInfo   # memory, VM count, templates, drain state
agent List       # VMs on the node
```

Delete `$D` and stop the port-forward when you are done.

## Alerts

### CraftFcHostAgentDown

**Meaning.** Prometheus cannot scrape the agent on one node for 5 minutes. The agent is down,
it restarts in a loop, or it refuses the metrics token (401). While the agent is down, the
api_server cannot place VMs on that node and VMs on the node have no egress. Running VMs
continue to run.

**Check.**

```bash
kubectl $K -n $NS get pods -o wide -l app.kubernetes.io/component=craft-fc-host-agent
kubectl $K -n $NS describe "$(pod_on <node>)"
kubectl $K -n $NS logs "$(pod_on <node>)" --tail=200 | grep -E '"level":"(ERROR|WARN)"|host agent'
kubectl $K -n $NS logs "$(pod_on <node>)" --previous --tail=100   # after a restart
```

- `host agent failed` in the log: the agent stopped at start-up. The error names the failed
  check (for example XFS reflink, cgroup v2, `/dev/kvm`, artifacts SHA256).
- `/metrics has no token` in the log: the metrics token Secret is empty or missing. Compare
  `craft.hostAgent.metrics.authExistingSecret` (or the chart copy) with `auth.metricsAuth`.
- The pod is Running and the log is clean: check the scrape target in Prometheus
  (Status > Targets) for 401 or a timeout.

**Fix.**

- Fix the cause that the log names, then delete the pod. The DaemonSet makes a new pod. VMs
  continue to run, and the new agent adopts them from the journal (`recovered VMs` in the log).
- For a 401 with a token, make the token in the agent namespace match `auth.metricsAuth`. The
  agent reads the token file on each scrape, so it needs no restart.
- For a 401 with no token (`auth.metricsAuth` off and `configMap.DISABLE_METRICS_AUTH` not
  `"true"`), the agent refuses every scrape. Set `auth.metricsAuth`, then deploy again. The chart
  copies the token to the agent namespace and the ServiceMonitor sends it.
- If `auth.metricsAuth` uses `existingSecret`, the chart cannot copy the token, and Helm fails
  without `craft.hostAgent.metrics.authExistingSecret`. Create a Secret with the same key in the
  agent namespace and set that value.
- Do not use `DISABLE_METRICS_AUTH: "true"` to fix a 401. It also removes the auth of the
  api_server and MCP server `/metrics`.

**Escalate** when the agent does not start after one restart, or when `recovered VMs` shows
`unresponsive` VMs.

### CraftFcHostAgentPodsMissing

**Meaning.** The DaemonSet has fewer available pods than it wants for 15 minutes. A sandbox node
without a Ready agent takes no new VMs. This rule needs kube-state-metrics.

**Check.**

```bash
kubectl $K -n $NS get ds $DS
kubectl $K -n $NS get pods -o wide -l app.kubernetes.io/component=craft-fc-host-agent
kubectl $K get nodes -l onyx.app/kvm=true
kubectl $K -n $NS get events --sort-by=.lastTimestamp | tail -20
```

- `Pending`: the node lacks resources, or a taint has no toleration.
- `Init:` state: the rootfs init container (`craft.hostAgent.rootfs`) cannot pull its image or
  copy the root drive.
- `ImagePullBackOff`: the agent image tag or the pull Secret in the agent namespace is wrong.

**Fix.** Fix the image, the pull Secret, the toleration or the node resources. Then delete the
failed pod.

**Escalate** when a node with `onyx.app/kvm=true` gets no agent pod after the fix.

### CraftFcCreateFailures

**Meaning.** More than 20% (and at least 3) of admitted Creates on one node failed in 15
minutes, for 10 minutes. "Failed" means the start failed after admission: the jailer, Firecracker,
the snapshot restore, the journal write or the guest key install.

**Check.**

```bash
kubectl $K -n $NS logs "$(pod_on <node>)" --since=30m | grep '"method":"Create"' | grep -v '"result":"OK"' | tail -20
agent NodeInfo
```

The audit line has `reason` (the ErrorReason). The dashboard panel "Admission refusals and
failures by reason" shows the reasons over time.

- `VMM_FAILED`: Firecracker or the restore failed. Read the guest log lines of that sandbox
  (`kind=guest_log`, `sandbox_id`) in the agent stdout.
- `SANDBOX_IN_DOUBT`: see "Clear a sandbox in doubt" below.
- `GUEST_KEY_REJECTED` or `GUEST_UNREACHABLE`: the guest daemon did not accept the key or did
  not answer. The template can be bad: see "Rebuild a template".

**Fix.** If one node fails and other nodes do not, drain that node (see "Drain a node") and
restart its agent. If all nodes fail after a release, roll back the agent image or the root drive.

**Escalate** when the failures continue on a new node, or after a rollback.

### CraftFcAdmissionRefusals

**Meaning.** One node refused 10 or more Creates with one node-side reason in 15 minutes, for 15
minutes. The api_server then tries the next node, so users see slow starts, or no start when all
nodes are full. The reasons in this rule:

| Reason | Cause |
|---|---|
| `CAPACITY_MEMORY` | `MemAvailable` < starting VMs + the new VM + `--min-free-mem-mib`, or the agent cannot read node memory |
| `CAPACITY_DISK` | The data disk has less free space than `--min-free-disk-gib`, or the agent cannot read it |
| `CAPACITY_VM_SLOTS` | The node runs `--max-vms` VMs (metadata `vm_count`, `max_vms`), no free jailer UID, or the process scan failed at start-up |
| `EGRESS_CA_UNAVAILABLE` | The agent cannot read the sandbox-proxy CA ConfigMap |
| `SANDBOX_IN_DOUBT` | The agent keeps a Firecracker process that it cannot verify |

`NODE_DRAINING` is not in this rule: a drain causes it.

**Check.**

```bash
agent NodeInfo
kubectl $K -n $NS logs "$(pod_on <node>)" --since=30m | grep -E 'CAPACITY_|EGRESS_CA|IN_DOUBT' | tail -10
```

The refusal message and `ErrorInfo.metadata` give the numbers (`mem_available_mib`,
`mem_needed_mib` and more). The dashboard row "Node memory and disk" shows the trend.

**Fix.**

- Capacity on all nodes: add sandbox nodes (node group size).
- Capacity on one node: look for VMs that should have stopped (`agent List`). Stop the ones the
  api_server does not know (see "Purge data").
- `CAPACITY_DISK`: look for large spools in `<data-dir>/captures` and old templates in
  `<data-dir>/templates` (`kubectl exec` into the agent pod; the data dir is
  `craft.hostAgent.dataDir`, default `/var/lib/craft-fc`). The image GC removes unused managed
  images and old templates after `--image-gc-grace` (6 h). The grace counts from the first pass that
  sees an image unused (every `--image-gc-interval`, 15 min), and starts again after an agent restart.
  `--image-gc-interval=0` turns the GC off, and templates are swept only after a template build from
  `--rootfs-dir`. Look for `image GC` in the agent log.
- `EGRESS_CA_UNAVAILABLE`: check the ConfigMap
  `kubectl $K -n <SANDBOX_NAMESPACE> get configmap <SANDBOX_PROXY_CA_CONFIGMAP>` and the agent
  Role `<DS>-egress-ca-read`.
- `CAPACITY_VM_SLOTS` with few VMs, or `SANDBOX_IN_DOUBT`: see "Clear a sandbox in doubt".

**Escalate** when the node has free memory and disk but still refuses, or when the refusals
continue after more nodes join.

### CraftFcSessionTransferFailures

**Meaning.** Three or more `CaptureSession`, `UploadCapture` or `RestoreSession` calls on one node
failed in 30 minutes (`Canceled` does not count). Session saves can be late or lost, and a user
can get an old session state.

**Check.**

```bash
kubectl $K -n $NS logs "$(pod_on <node>)" --since=1h \
  | grep -E '"method":"(CaptureSession|UploadCapture|RestoreSession)"' | grep -v '"result":"OK"' | tail -20
```

| Reason | Cause |
|---|---|
| `TRANSFER_FAILED` | Network error or a non-2xx status from object storage |
| `ARCHIVE_MISMATCH` | The size or SHA-256 does not match what the api_server signed |
| `CAPTURE_TOO_LARGE` | The archive is larger than `--capture-max-bytes` |
| `CAPTURE_NOT_FOUND` | The spool expired (`--capture-ttl`) or the agent restarted |
| `CAPACITY_DISK` | No disk for the spool |

**Fix.**

- `TRANSFER_FAILED` on all nodes: check object storage (bucket, endpoint, presigned URL expiry)
  and the node egress to it.
- `ARCHIVE_MISMATCH` or `CAPTURE_NOT_FOUND`: the api_server repeats the capture. Look for a
  version mismatch between the api_server and the agent.
- `CAPTURE_TOO_LARGE`: the session is too large for the limit. Raise `--capture-max-bytes` only
  with enough disk.

**Escalate** at once when restores fail: users can lose work.

### CraftFcRelayErrors

**Meaning.** More than 10% (and at least 10) of egress relay connections on one node failed in
10 minutes, for 10 minutes. `upstream_failed`: sandbox-proxy did not answer an accepted
connection. `over_cap`: a VM opened more than `--relay-max-conns` connections.

**Check.**

```bash
kubectl $K -n $REL get pods -l app.kubernetes.io/component=sandbox-proxy -o wide
kubectl $K -n $REL logs deploy/onyx-sandbox-proxy --since=30m | grep -iE 'error|reject' | tail -20
kubectl $K -n $NS logs "$(pod_on <node>)" --since=30m | grep -E 'signing key regist|"level":"ERROR"' | tail -10
```

The dashboard panel "Relay connections by result" shows which result grows.

**Fix.**

- `upstream_failed` on all nodes: sandbox-proxy is down or full. Fix or scale it.
- `upstream_failed` on one node: check the NetworkPolicy from the agent namespace to the proxy
  port, and that the node key is registered (`node signing key registered` in the agent log).
- `over_cap` from one VM: a user program opens too many connections. The cap protects the node;
  no fix is necessary unless many VMs hit it.

**Escalate** when the proxy is healthy and the node key is registered, but the errors continue.

### CraftFcNodeMemoryLow

**Meaning.** One node has less than 10% of its memory available for 15 minutes. New VMs on that
node get `CAPACITY_MEMORY`. The cgroup OOM killer can stop a VM.

**Check.**

```bash
agent NodeInfo   # mem_available_mib, mem_reserve_mib, mem_starting_mib
agent List
kubectl $K top node <node>
```

Compare "Guest memory allocated vs node memory" on the dashboard. When "in use" is near
"allocated", the guests use their memory and the balloon cannot give back more.

**Fix.**

- Add sandbox nodes, so that placement uses them.
- Drain the node (see "Drain a node") if one node stays full and others have space.
- Stop VMs that the api_server does not know (see "Purge data").

**Escalate** when VMs on the node are OOM-killed (`EXITED` in `agent List`, OOM in the node
kernel log), or when host processes other than VMs use the memory.

### CraftFcTemplateUnusable

**Meaning.** For 15 minutes, a node refused Creates with `TEMPLATE_MISSING` or
`TEMPLATE_INCOMPATIBLE`, or a `BuildTemplate` call failed. The node cannot start VMs for that
template.

The alert also fires when `craft_fc_host_agent_template_ready` is 0: the node has no usable
template from its root drive, for example after a failed start-up build. The agent log names the cause.

**Check.**

```bash
kubectl $K -n $NS logs "$(pod_on <node>)" | grep -E 'template (ready|build|GC)'
agent NodeInfo   # templates on the node and their keys
```

- `template build at start-up failed`: the root drive is missing or wrong, the build timed out,
  or the egress CA does not fit.
- `TEMPLATE_INCOMPATIBLE`: the message names the key fields that differ (Firecracker version, CPU
  model, host kernel, guest kernel, CA) or the template file that changed.

**Fix.** See "Rebuild a template".

**Escalate** when a fresh build fails on a node of the same type as nodes that work.

## Procedures

### Drain a node

Running VMs keep running during a drain. The api_server does not move them yet. Stop them after
their sessions are saved.

1. Set the manual drain flag first. It stays set across agent restarts:
   `agent SetDrain '{"drain": true}'`.
2. Cordon the node: `kubectl $K cordon <node>`. The agent sees the taint within
   `--drain-poll-interval` (10 s).
3. New Creates on the node now get `NODE_DRAINING`, and the api_server uses other nodes.
4. List the VMs (`agent List`). Make sure that the api_server saved each session. Then stop each VM:
   `agent Stop '{"sandbox_id": "<id>", "attempt": <n>, "generation": <n>}'`.
5. Wait until `agent NodeInfo` shows `drain.state` `DRAINED`. Then remove or repair the node.
6. To put the node back: `kubectl $K uncordon <node>` and `agent SetDrain '{"drain": false}'`.

### Rebuild a template

The agent builds its template from the root drive at start-up and on `BuildTemplate`. A valid
template with the same key is not built again.

- New root drive: set `craft.hostAgent.rootfs.image.tag` to the new version and deploy. The init
  container copies the drive, and the new agent builds the template at start.
- Same root drive, bad template: delete the agent pod. At start, the agent checks the template
  and builds it again if the check fails. It does not rebuild a template that a VM uses.
- On demand: `agent BuildTemplate`. A draining node refuses a build that must boot a VM.
- Read the result in the log: `template ready` with `built` and `build_ms`.

### Clear a sandbox in doubt

`SANDBOX_IN_DOUBT` means that the agent keeps a Firecracker process that it cannot verify. The
agent never kills a process on doubt.

1. Repeat the Create or Stop. The agent scans the processes again first. If the process is gone,
   the doubt clears.
2. Read the agent log for the journal record of the sandbox
   (`<data-dir>/journal/<sandbox_id>.json`).
3. If the process is not a VM that a user needs, remove the journal record and restart the agent.
   The agent then kills the process as an orphan.

Escalate before you remove a record of a VM that a user can still use.

### Restore a user session

The api_server owns session saves and restores: it calls `CaptureSession`, `UploadCapture` and
`RestoreSession` with presigned URLs. Automatic saves before a stop are not built yet. There is no
operator command to restore a session by hand. If a user lost a session, escalate with the
sandbox ID, the tenant ID and the time.

### Purge data

- A VM: `agent Stop` removes the VM chroot, its scratch disk and its relay identity. The journal
  keeps a `stopped` tombstone for 24 h. The tombstone has no user data.
- Capture spools: the agent deletes a spool after a successful upload, after `--capture-ttl` (15
  min) and at each start.
- Session archives in object storage: the api_server owns them. The agent has no storage
  credentials.
- A whole node: drain it, then delete the node. VM data is only on the node data disk.

## Signals with no metric

These have no Prometheus metric yet. Use the agent log:

| Signal | Log line |
|---|---|
| Node state report push | `node state report failed` (with `failures`), then `node state report sent again` |
| Node key registration | `node signing key registered` or `node signing key registration failed` |
| Start-up template build | `template ready` or `template build at start-up failed` |
| Balloon reclaim | none. The dashboard compares guest memory allocated with node memory in use |
