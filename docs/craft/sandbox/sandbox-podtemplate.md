# Codify the sandbox Pod spec into Helm (PodTemplate)

## Issues to Address

The per-sandbox Pod spec is constructed field-by-field in Python
(`KubernetesSandboxManager._create_sandbox_pod`, ~230 lines). Everything in it
except a handful of per-pod values is static infrastructure config — container
images, ports, volumes, security contexts, init/sidecar containers, node
selector, tolerations, resource sizing, proxy CA wiring. This duplicates what
Helm already owns for the rest of the sandbox stack (namespace, RBAC, network
policy, egress proxy — all in `deployment/helm/charts/onyx/templates/`) and
means any change to the pod's shape requires a backend image rebuild + deploy
rather than a `helm upgrade`.

Goal: move the static shape of the sandbox Pod into a Helm-rendered
`core/v1` **PodTemplate**, leaving Python to read it and overlay only the
genuinely dynamic per-pod fields.

## Important Notes

- **Why PodTemplate, not a plain resource:** the Pod is created per-user at
  request time, so it can't be a static Helm Pod. `core/v1 PodTemplate` is the
  typed, first-class K8s object designed exactly for "declare the shape at
  deploy time, instantiate at runtime." Prefer it over a ConfigMap-carried YAML
  (untyped, unvalidated).
- **Only four fields are dynamic** and must stay in Python:
  1. `metadata.name` (`sandbox-{uuid[:8]}`)
  2. `metadata.labels` — `LABEL_SANDBOX_ID`, `LABEL_TENANT_ID` merged onto the
     template's base labels
  3. the two `secretKeyRef.name` env entries on the sandbox container, pointing
     at the per-pod `{pod}-opencode-auth` Secret
  4. `spec.hostAliases[0].ip` — the proxy ClusterIP resolved at runtime by
     `_resolve_proxy_ip()` (DNS to the proxy is blocked by the firewall, so this
     can't be static)
- **Everything else is static** and moves into the template: both containers
  (`sandbox` + `sidecar`), the `sandbox-init` init container (NET_ADMIN +
  `firewall-init.sh`), `workspace`/`managed` emptyDirs, CA source/bundle
  volumes, pod + container security contexts, `nodeSelector`,
  `tolerations`, `enableServiceLinks: false`, probes, and the proxy env
  constants from `_proxy_main_container_env_vars()` /
  `_proxy_init_container()`.
- **The Service stays in Python.** K8s has no `ServiceTemplate` object, and
  `_create_sandbox_service` is ~30 lines (names + the Next.js port range). Do
  NOT try to template it. Instead single-source the port range
  (`SANDBOX_NEXTJS_PORT_START`/`END`) so the template's container/service ports
  and the Python service can't drift.
- **Resource sizing is already half-codified** via `SANDBOX_POD_CPU_REQUEST`
  etc. (`configs.py`), injected from the Helm ConfigMap. These move into the
  PodTemplate values and the env vars in `configs.py` are retired (or kept only
  as the template's value source — pick one source of truth, prefer the
  template).
- **Image ownership:** the PodTemplate defaults all sandbox containers to
  `onyxdotapp/sandbox:${global.version}`. `SANDBOX_CONTAINER_IMAGE` remains an
  internal override, but the chart owns the normal Kubernetes image default.
- **Version skew is the main risk.** A PodTemplate rendered by an older chart
  against a newer api-server (or vice versa). The overlay code must be
  defensive — append the secret-env entries and hostAliases in Python rather
  than assuming list indices in the template. Keep the template free of any
  per-pod knowledge (no placeholder secret names to find-and-replace).
- **New runtime dependency / failure mode:** the api-server now requires the
  PodTemplate to exist in `SANDBOX_NAMESPACE` at provision time. Add a clear
  error (and ideally a one-time startup check when `ENABLE_CRAFT` +
  `SANDBOX_BACKEND=kubernetes`) so a missing/misnamed template fails loudly
  rather than deep inside `provision()`.
- Gate the new template on `ENABLE_CRAFT` via the existing
  `onyx.craftEnabled` helper in `_helpers.tpl`, matching the other sandbox
  templates.

## Implementation Strategy

1. **Add `templates/sandbox-podtemplate.yaml`** rendering a `v1/PodTemplate`
   named e.g. `sandbox-pod` into `SANDBOX_NAMESPACE`. Its `.template.spec` is
   the full static pod spec; `.template.metadata.labels` carries the static
   labels (`LABEL_K8S_COMPONENT`, `LABEL_K8S_MANAGED_BY`). Drive all tunables
   from a new `sandboxPod:` block in `values.yaml`.

2. **Add the `sandboxPod:` values block** exposing: `image`, `imagePullPolicy`,
   the Next.js port range, the three resource sets (sandbox / sidecar / init),
   `nodeSelector`, `tolerations`, and CA mount config. Wire CI/localdev
   overlays (`values-ci.yaml`, `values-localdev.yaml`) — CI overrides the
   resource requests for the 4-vCPU kind runner exactly as the env vars do
   today.

3. **Rewrite `_create_sandbox_pod`** to:
   `read_namespaced_pod_template(name, SANDBOX_NAMESPACE)` →
   `copy.deepcopy(tpl.template.spec)` → overlay the four dynamic fields →
   return `V1Pod(metadata=..., spec=...)`. Delete the static construction.
   Keep `_proxy_init_container`/`_proxy_main_container_env_vars` only if still
   referenced; otherwise remove.

4. **Single-source the port range** between the template and
   `_create_sandbox_service` (config constant feeding both). Leave the Service
   construction in Python.

5. **Add a startup/preflight check** that the PodTemplate exists when
   `ENABLE_CRAFT` and the K8s backend are active, raising a clear error
   naming the expected template + namespace.

6. **Retire** the now-template-owned env vars from `configs.py`
   (`SANDBOX_POD_CPU_*`, `SANDBOX_POD_MEMORY_*`, and the image default if fully
   migrated), updating any other readers.

## Tests

- **Integration test (kind, primary):** provision a sandbox against the kind
  cluster (see the existing kind integration-test env in CLAUDE.md / memory) and
  assert the resulting Pod has the expected containers, volumes, security
  context, node selector, the correct `secretKeyRef` names, and a resolved
  `hostAliases` IP. This is the real coverage — it exercises template-read +
  overlay end to end.
- **Helm:** `helm template` + lint with `ENABLE_CRAFT=true` across
  default/CI/localdev values to confirm the PodTemplate renders and the
  resource/port values flow through. Confirm it does NOT render when
  `ENABLE_CRAFT` is false.
- **External-dependency unit test (optional):** mock `read_namespaced_pod_template`
  to return a known template and assert the overlay sets exactly the four
  dynamic fields and nothing else — guards the version-skew contract.

Do not overtest — the kind integration test plus helm template lint is the core
of the coverage.
