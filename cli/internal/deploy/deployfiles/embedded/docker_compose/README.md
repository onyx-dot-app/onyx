# Welcome to Onyx

To set up Onyx there are several options, Onyx supports the following for deployment:
1. Quick guided install via the install.sh script
2. Pulling the repo and running `docker compose up -d` from the deployment/docker_compose directory
  - Note, it is recommended to copy over the env.template file to .env and edit the necessary values
3. For large scale deployments leveraging Kubernetes, there are two options, Helm or Terraform.

This README focuses on the easiest guided deployment which is via install.sh.

**For more detailed guides, please refer to the documentation: https://docs.onyx.app/deployment/overview**

## install.sh script

```
curl -fsSL https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.sh > install.sh && chmod +x install.sh && ./install.sh
```

The script installs the Onyx CLI (`onyx-cli`) and hands over to `onyx-cli deploy install`, which is
where the guided installation lives. Any flags you pass are forwarded to it. If you already have the
CLI (`pip install onyx-cli`), skip the script and run `onyx-cli deploy install` directly.

This provides a guided installation of Onyx via Docker Compose. It will deploy the latest version of Onyx
and set up the volumes to ensure data is persisted across deployments or upgrades.

The deployment files are stored in `~/.config/onyx` (an existing `onyx_data` directory from an older
install is detected and kept in place; `--dir` targets another location). Note that no application
critical data is stored in that directory so even if you delete it, the data needed to restore the app
will not be destroyed.

The data about chats, users, etc. are instead stored as named Docker Volumes. This is managed by Docker
and where it is stored will depend on your Docker setup. You can always delete these as well by running
`onyx-cli deploy uninstall`.

To shut down the deployment without deleting, use `onyx-cli deploy stop`.

### Managing the deployment

Beyond installing, the CLI covers the rest of the lifecycle:

| Command | What it does |
| --- | --- |
| `onyx-cli deploy status` | Installed version, containers, and health (`--json` for scripts) |
| `onyx-cli deploy logs [service...]` | Logs of the deployment's containers |
| `onyx-cli deploy stop` | Stop the containers, keep the data |
| `onyx-cli deploy upgrade [--tag vX.Y.Z]` | Upgrade in place (see below) |
| `onyx-cli deploy uninstall` | Remove the containers, volumes, and deployment directory |

### Upgrading the deployment
Onyx maintains backwards compatibility across all minor versions following SemVer, so upgrading is
`onyx-cli deploy upgrade` (add `--tag vX.Y.Z` to pin a version). It rewrites only IMAGE_TAG, preserves
your .env edits, and backs up hand-edited files.

If you are more comfortable running docker compose commands, you can also run commands directly from
the directory with the docker-compose.yml file. First bring the containers down (`docker compose down`),
verify the version you want in the environment file (see below), (if using `latest` tag, be sure to run
`docker compose pull`) and run `docker compose up` to restart the services on the latest version

A hand-run upgrade from a release before v5.0 of an install on the bundled MinIO (`.env` has
`S3_ENDPOINT_URL=http://minio:9000`) needs two more `.env` edits before `docker compose up`, since v5.0
moves the bundled file store from MinIO to the object store and only `onyx-cli deploy upgrade` makes them
for you: set `S3_ENDPOINT_URL=http://object-store:8333` and add `S3_LEGACY_ENDPOINT_URL=http://minio:9000`.
Keep `MINIO_REPLICAS` unset or `1` until you retire MinIO, since it still holds the files. Without the two edits the app keeps its files in MinIO, which a later release removes. The `api_server` and
`object-store-copy` logs warn about this at startup. External storage (S3, GCS, Azure) needs no change. See
the [object store migration guide](https://docs.onyx.app/admins/advanced_configs/object_store_migration).

### Rolling back the deployment
A rollback does not change the database schema. An older release fails to start on a newer schema with
`Can't locate revision`. Only the newer image has the migrations to downgrade it. The downgrade deletes data
that only the newer release stores.

First get the last migration of the target release. For v4.9 it is `25053020dd5a`.

```bash
docker run --rm onyxdotapp/onyx-backend:<target version> alembic heads
```

Then downgrade with the newer image and roll back immediately. Run the downgrade in the directory with the
compose files. On a prod install, add `-f docker-compose.prod.yml` after `docker compose`. If
`docker compose ls` shows a project name other than `onyx`, add `-p <project>`. Run `onyx-cli` from where you
usually run it, or pass `--dir <install root>`. It warns that downgrades are not supported. Continue, because
the schema now matches.

```bash
IMAGE_TAG=<newer version> docker compose run --rm --no-deps api_server alembic downgrade <target migration>
onyx-cli deploy upgrade --tag <target version> --allow-downgrade
```

If you rolled back first and `api_server` restarts in a loop, run the same downgrade command. `api_server`
then starts on the target release.

### Customizing the compose files
The CLI owns the compose files it writes. Each `onyx-cli deploy upgrade` refreshes them to match the
new version. If you edit one, the CLI asks before it replaces the file, and it keeps a backup — but
your edits are not applied again.

To customize the deployment, put your changes in a file next to `docker-compose.yml`, named
`compose.override.yml`, `compose.override.yaml`, `docker-compose.override.yml`, or
`docker-compose.override.yaml`. These are the same names `docker compose` finds on its own; if more than
one is present, the CLI picks the same one Compose would, in that order. The CLI applies that file last,
after its own files, so your changes win. The CLI does not manage the override: it never writes,
replaces, or backs it up, and an upgrade does not touch it. `install`, `upgrade`, `stop`, `logs`, and
`uninstall` all apply it.

For example, to put Onyx behind your own reverse proxy, stop nginx from publishing a host port and
attach it to your proxy's network:

```yaml
# deployment/docker-compose.override.yml
services:
  nginx:
    # !reset replaces the list. Without it, Compose adds to the list.
    ports: !reset []
    networks: [default, proxy]

networks:
  proxy:
    external: true
```

Use `docker compose -f docker-compose.yml -f docker-compose.override.yml config` in the deployment
directory to see the merged result. Add each file the CLI applies (`docker-compose.onyx-lite.yml`,
`docker-compose.prod.yml`, and so on) in the same order the CLI does.

### Environment variables
The Docker Compose files try to look for a .env file in the same directory. The installer sets it up
from a file called env.template. Feel free to edit the .env file to customize your deployment. The most
important / common changed values are located near the top of the file. Later `onyx-cli deploy` runs
keep your edits.

IMAGE_TAG is the version of Onyx to run. It is recommended to leave it as latest to get all updates with each redeployment.

Every image publishes a `-dev` twin for each of its tags (e.g. `latest-dev`, `v1.2.3-dev`), so a single
`IMAGE_TAG=latest-dev` selects the dev variant of the whole deployment. Today only the backend image actually differs:
its `-dev` twin adds interactive debugging tools (vim, nano, curl, ps, psql) that the default image leaves out to stay
minimal. The web-server, model-server, and sandbox `-dev` tags are identical to their plain counterparts and exist so
that one version string covers every image.

### Load a license file at startup

Self-hosted deployments can load a signed `.lic` file when the API server starts.
This also works without network access.

Set the container path in your deployment's `.env` file:

```dotenv
ONYX_LICENSE_FILE=/run/onyx/license.lic
```

Mount your license file into `api_server` with a Compose override:

```yaml
# docker-compose.override.yml
services:
  api_server:
    volumes:
      - type: bind
        source: /absolute/path/to/onyx-license.lic
        target: /run/onyx/license.lic
        read_only: true
        bind:
          create_host_path: false
```

Replace `source` with the file's absolute host path. The API process must have permission to read the file.
Use an absolute container path for `ONYX_LICENSE_FILE`. Relative paths start at the API process working directory.
The environment setting does not mount the host file automatically.

Start or recreate the API server with your deployment's existing Compose files, in the same order.
Append the license override last. For a standard deployment:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d api_server
```

For a production deployment:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.override.yml up -d api_server
```

For a Lite deployment:

```bash
docker compose -f docker-compose.yml -f docker-compose.onyx-lite.yml \
  -f docker-compose.override.yml up -d api_server
```

Keep any other active overlays, such as Craft or dev ports, before the license override.

At each startup, Onyx verifies the file's signature and stores the license in PostgreSQL.
It keeps a stored license that has a later issue time and updates the license cache.
After the container starts, missing, unreadable, empty, or invalid license files produce an error log.
The API continues with the stored license.
The host source must exist before Compose creates or recreates `api_server`.
With `create_host_path: false`, Compose rejects a missing source before the API starts.
Multi-tenant deployments ignore this setting.

Removing `ONYX_LICENSE_FILE` does not delete the stored license. Remove the setting before you delete or downgrade a license.
Otherwise, a later API restart can restore the license from the file.

### Self-hosted embedding models and air-gapped deployments
The model-server image contains one embedding model: `ibm-granite/granite-embedding-97m-multilingual-r2`,
the default for new installs. It works with no network access.

The model servers download all other self-hosted embedding models from Hugging Face the first time
they use them. This includes `nomic-ai/nomic-embed-text-v1`, which older images contained. The
downloads go to the `model_cache_huggingface` and `indexing_huggingface_model_cache` volumes.
When a model is in these volumes, the model servers load it from there with no network access. An
upgrade keeps the models that are already in the volumes.

For an air-gapped deployment:
- Keep these volumes when you upgrade. Do not delete them.
- To use a self-hosted model that is not in the volumes, give the model servers network access to
  Hugging Face once, or copy the model into the Hugging Face cache in both volumes before you select it.
  Onyx loads its recommended self-hosted models at the revision that
  `backend/shared_configs/embedding_models.py` pins, so copy that revision.
