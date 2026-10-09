# Kubernetes development in Zed

1. Install Process Compose: `brew install f1bonacc1/tap/process-compose`.
2. Run `make craft-up` from the repository root, then fill in `.vscode/.env.k8s`.
3. Stop any local services using ports 3000 or 8080.
4. Open the task picker (`Cmd+Shift+R`) and run `run: all services (k8s)`.

Use `Ctrl+R` to restart a service and `F10` to stop the stack.
Logs are available in Process Compose and `.zed/logs/`.
For CLI access, use `process-compose --port 18080`.

For VPN or proxy certificate errors, see
[manual CA setup](../docs/craft/dev/local-kubernetes.md#vpn-or-proxy-certificate-errors).
