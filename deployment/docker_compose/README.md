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

This provides a guided installation of Onyx via Docker Compose. It will deploy the latest version of Onyx
and set up the volumes to ensure data is persisted across deployments or upgrades.

The script will create an onyx_data directory, all necessary files for the deployment will be stored in
there. Note that no application critical data is stored in that directory so even if you delete it, the
data needed to restore the app will not be destroyed.

The data about chats, users, etc. are instead stored as named Docker Volumes. This is managed by Docker
and where it is stored will depend on your Docker setup. You can always delete these as well by running
the install.sh script with --delete-data.

To shut down the deployment without deleting, use install.sh --shutdown.

### Upgrading the deployment
Onyx maintains backwards compatibility across all minor versions following SemVer. If following the install.sh script (or through Docker Compose), you can
upgrade it by first bringing down the containers. To do this, use `install.sh --shutdown`
(or `docker compose down` from the directory with the docker-compose.yml file).

After the containers are stopped, you can safely upgrade by either re-running the `install.sh` script (if you left the values as default which is latest,
then it will automatically update to latest each time the script is run). If you are more comfortable running docker compose commands, you can also run
commands directly from the directory with the docker-compose.yml file. First verify the version you want in the environment file (see below),
(if using `latest` tag, be sure to run `docker compose pull`) and run `docker compose up` to restart the services on the latest version

## Compose file layout

`docker-compose.yml` is the base file and the single source of truth for all
service definitions (services, healthchecks, volumes, defaults). Deployment
modes are thin overlay files layered on top with `-f`:

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Base — every service, healthchecks, dev-friendly defaults |
| `docker-compose.dev.yml` | Exposes service ports on the host for development/testing |
| `docker-compose.prod.yml` | Production hardening + Let's Encrypt HTTPS + certbot renewal |
| `docker-compose.prod-no-letsencrypt.yml` | Production hardening + user-provided SSL certificates |
| `docker-compose.onyx-lite.yml` | Minimal deployment (Postgres only; no search/background/model servers) |
| `docker-compose.craft.yml` | Opt-in Craft Docker sandbox backend (`install.sh --include-craft`) |

Configuration comes from `.env` in this directory (start from `env.template`,
or `env.prod.template` for production). The production overlays additionally
read nginx domain/certificate settings from `.env.nginx` (see
`env.nginx.template`). The `s3-filestore` entry in `COMPOSE_PROFILES`
controls whether the bundled MinIO runs.

Examples:

```
# development with exposed service ports
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --wait

# production with Let's Encrypt (run ./init-letsencrypt.sh once first)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --wait
```

Instead of repeating `-f` flags, set `COMPOSE_FILE` in `.env`
(e.g. `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`) and use plain
`docker compose up -d`.

### Environment variables
The Docker Compose files try to look for a .env file in the same directory. The `install.sh` script sets it up from a file called env.template which is
downloaded during the initial setup. Feel free to edit the .env file to customize your deployment. The most important / common changed values are
located near the top of the file.

IMAGE_TAG is the version of Onyx to run. It is recommended to leave it as latest to get all updates with each redeployment.
