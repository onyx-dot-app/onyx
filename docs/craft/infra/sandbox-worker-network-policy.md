# Sandbox worker NetworkPolicy

Craft sandboxes have default-deny ingress. The Helm chart adds explicit ingress
from api_server and scheduled-task workers to the ports they need:

- `4096` for `opencode serve`
- the configured generated-app preview range

Snapshots and managed-content pushes no longer use an HTTP sidecar port. They
run through the root helper over Kubernetes `exec`, so no worker policy should
open a push or snapshot port.

Keep the worker allow-list aligned with the code paths that call live
sandboxes. If a new worker needs to contact `opencode serve`, add only that
worker's stable labels and only the needed ports.

Verify with Helm render tests and a real sandbox flow that snapshots, previews,
and approvals still work under NetworkPolicy.
