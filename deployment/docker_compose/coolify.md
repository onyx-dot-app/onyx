# Onyx on Coolify

Coolify can run Onyx from the existing Docker Compose stack.

## Recommended setup

- **Resource type:** Docker Compose
- **Repository:** this repo
- **Base directory:** `deployment/docker_compose`
- **Compose file:** `docker-compose.prod-no-letsencrypt.yml`
- **Public entrypoint:** the `nginx` service
- **Persistent data:** keep the `../data` directory and the named Docker volumes created by the stack

## Environment variables

Copy the values from `env.template` into Coolify's environment editor.
The minimum values you should set explicitly are:

- `IMAGE_TAG=latest`
- `USER_AUTH_SECRET=<random hex>`
- `POSTGRES_USER=<your postgres user>`
- `POSTGRES_PASSWORD=<your postgres password>`
- `WEB_DOMAIN=https://your-domain.example`
- `COMPOSE_PROFILES=s3-filestore`
- `FILE_STORE_BACKEND=s3`

If you want to use PostgreSQL for file storage instead of MinIO, set `FILE_STORE_BACKEND=postgres` and remove `s3-filestore` from `COMPOSE_PROFILES`.

## Notes for Coolify

- Coolify already provides TLS termination, so keep only one public ingress path.
- If your Coolify deployment template insists on publishing host ports, remove the `ports:` block from the `nginx` service before applying the compose file.
- If you want a smaller footprint, you can also use `docker-compose.onyx-lite.yml` as the base overlay and enable only the services you need.
