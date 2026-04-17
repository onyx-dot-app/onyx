# Onyx Local Monitoring Stack

Prometheus + Grafana for local development. Pre-loaded with dashboards for the Onyx backend.

## Usage

```bash
cd profiling/
docker compose up -d
```

| Service    | URL                          | Credentials   |
|------------|------------------------------|---------------|
| Grafana    | http://localhost:3001        | admin / admin |
| Prometheus | http://localhost:9090        | —             |

## Dashboards

- **Onyx DB Pool Health** — PostgreSQL connection pool utilization
- **Onyx Indexing Pipeline v2** — Per-connector indexing throughput, queue depth, task latency

## Scrape targets

| Job                      | Port  | Source                        |
|--------------------------|-------|-------------------------------|
| `onyx-api-server`        | 8080  | FastAPI `/metrics` (matches `.vscode/launch.json`) |
| `onyx-monitoring-worker` | 9096  | Celery monitoring worker      |
| `onyx-docfetching-worker`| 9092  | Celery docfetching worker     |
| `onyx-docprocessing-worker`| 9093 | Celery docprocessing worker  |

## Environment variables

Override defaults with a `.env` file in this directory or by setting them in your shell:

| Variable            | Default | Description                     |
|---------------------|---------|---------------------------------|
| `PROMETHEUS_PORT`   | `9090`  | Host port for Prometheus UI     |
| `GRAFANA_PORT`      | `3001`  | Host port for Grafana UI        |
| `GF_ADMIN_PASSWORD` | `admin` | Grafana admin password          |

## Editing dashboards

`allowUiUpdates: true` is set in the provisioning config, so you can edit dashboards in the Grafana UI. However, **changes don't persist** across `docker compose down` — to keep edits, export the dashboard JSON and overwrite the file in `grafana/dashboards/onyx/`.
