# DEVCONTAINER OVERLAY

Running **inside the Onyx dev container**. These notes are additive to the root
`/workspace/CLAUDE.md`; on conflict with a host-oriented instruction there, prefer these.

## No Docker daemon in here

Don't use `docker` / `docker exec` / `docker compose`. Onyx services run as sibling
containers on the `onyx_default` network, reachable directly by hostname — so the root
guide's `docker exec -it onyx-relational_db-1 psql ...` won't work. Use
`psql -h relational_db -U postgres -c "<SQL>"` instead.

## Service hostnames (`onyx_default` network)

Each is also exported as an env var:

- Postgres: `relational_db` (`POSTGRES_HOST`)
- Redis: `cache` (`REDIS_HOST`)
- Vespa: `index` (`VESPA_HOST`)
- Model server: `inference_model_server` (`MODEL_SERVER_HOST`)
- OpenSearch: `opensearch` (`OPENSEARCH_HOST`)
- MinIO / S3: `minio:9000` (`S3_ENDPOINT_URL=http://minio:9000`)
