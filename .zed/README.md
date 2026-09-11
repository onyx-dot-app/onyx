# Onyx Kubernetes development in Zed

First, create the local cluster with `deployment/helm/dev/k8s-up.sh`. Copy
`.vscode/.env.k8s.template` to `.vscode/.env.k8s`, then set its required
values. Install Process Compose with
`brew install f1bonacc1/tap/process-compose`.

Open Zed's task picker with `Cmd+Shift+R`. Run
`run: all services (k8s)`.

The task performs the same Telepresence setup as the VS Code k8s launch,
refreshes cluster-generated secrets in `.vscode/.env.k8s`, and starts the web,
API, Celery workers, and Celery beat processes in Process Compose.

Process logs are visible per service in the Process Compose TUI and persist in
`.zed/logs/`. Logs rotate at 20 MB and retain three compressed backups for up
to seven days.

Useful controls:

- Arrow keys: select a process and inspect its logs.
- `F7`: start the selected process.
- `F9`: stop the selected process.
- `Ctrl+R`: restart the selected process.
- `F10`: stop the entire stack and leave the API Telepresence intercept.
- `Ctrl+Q`: show the process graph.
- `:`: open the Process Compose command palette.

The Process Compose control server uses `localhost:18080`, not its default
port 8080, because the Onyx API uses port 8080. From another terminal:

```bash
process-compose --port 18080 process list
process-compose --port 18080 process logs api --follow
process-compose --port 18080 process restart celery_primary
process-compose --port 18080 down
```

The task runs services without a debugger.
