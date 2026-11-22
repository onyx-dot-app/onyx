# Kubernetes development in Zed

1. Install Process Compose: `brew install f1bonacc1/tap/process-compose`.
2. Run `make craft-up` from the repository root. Use `.vscode/.env.k8s` for personal overrides.
3. Stop any local services using ports 3000 or 8080.
4. Open the task picker (`Cmd+Shift+R`) and run `run: all services (k8s)`.

Use `Ctrl+R` to restart a service and `F10` to stop the stack.
Logs are available in Process Compose and `.zed/logs/`.
For CLI access, use `process-compose --port 18080`.

For VPN or proxy certificate errors, see
[Refresh images](../deployment/helm/dev/README.md#refresh-images).

Startup uses `make craft-intercept`. It reuses an active intercept and retries a known stale-agent failure after restarting the API deployment.
The API and workers use the shared Craft launcher to read deployed settings and secrets into memory.
Startup does not write secrets to `.vscode/.env.k8s`. Existing entries remain overrides; remove obsolete chart-owned values when needed.

The `ready` process checks API readiness through the frontend and confirms that the frontend serves HTML.
It exits successfully once both are ready. If readiness times out, Process Compose stops the stack and reports failure.
