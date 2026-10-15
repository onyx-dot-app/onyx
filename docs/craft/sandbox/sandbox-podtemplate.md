# Sandbox PodTemplate

The Helm chart owns the static Craft sandbox pod shape in
`deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`. Python reads
that `PodTemplate` and overlays only per-sandbox names, labels, auth Secret
references, and proxy host aliases.

Current pod contract:

- `runtimeClassName` defaults to `kata-fc`.
- The pod has one `sandbox` main container.
- The pod has one `sandbox-firewall` init container.
- The init container owns firewall setup and is the only container with
  `NET_ADMIN`.
- The main container has only `SETUID`, `SETGID`, `SETPCAP`, and `CHOWN`.
- There is no sidecar, push port, workspace `emptyDir`, or pod `fsGroup`.
- The proxy CA mount is read-only.

The Service still stays in Python because Kubernetes has no `ServiceTemplate`.
Keep the preview port range single-sourced between Helm values and backend
config.

Verify changes with Helm render tests and a real KVM-backed integration run.
