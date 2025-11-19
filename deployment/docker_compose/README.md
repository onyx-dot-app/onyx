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

### Environment variables
The Docker Compose files try to look for a .env file in the same directory. The `install.sh` script sets it up from a file called env.template which is
downloaded during the initial setup. Feel free to edit the .env file to customize your deployment. The most important / common changed values are
located near the top of the file.

IMAGE_TAG is the version of Onyx to run. It is recommended to leave it as latest to get all updates with each redeployment.
