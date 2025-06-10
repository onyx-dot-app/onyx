# Mamamia README

There is an upstream Onyx README.md, which this file obsures. Check it out too.

## Why does this exist?

This is a fork of the Onyx repo aimed at fixing a few bugs and enabling some extra functionality. At the moment that includes:
- fixing the Gmail connector to make it robust against malformed date strings
- sending `User.email` as an extra body param to LLMs (to enable n8n to do things on a per-user basis)
- adding docker config and deployment scripts for GCP instances with a GPU attached

## Branches

- `main` is whatever the target release of upstream Onyx is, plus a change to the build script to build from source (see below)
- `release` is `main` plus any extra changes we want as part of our fork

## Deployment

To deploy this fork, you need to build it from source which is NOT the default behaviour for Onyx. The final command in both `init-letsencrypt.sh` and `init-letsencrypt-gpu.sh` has been modified to have a `--build` flag which will make that happen.

### GPU support

This fork includes changes to the docker config and deployment scripts to add support for GPUs. Use the `init-letsencrypt-gpu.sh` script.

See the `feature/terraform` branch (specifically the boot scripts running in https://github.com/mamamia/onyx/blob/e23831497ca2c9e64df954575c1d49717cd17d7f/deployment/terraform/instance/first_boot.tf) to learn how to configure the VM instance drivers to talk to an attached GPU.

### Troubleshooting

#### Logs

To view logs, do the following:
- ssh into the instance (see below)
- `sudo docker ps` will show you the available Containers
- run `sudo docker logs -f <container-name>`, where `<container-name>` is something like `onyx-stack-nginx-1`

#### Cert woes

Sometimes the build scripts don't work properly and you'll see the `api_server` fail to start because it can't see any certificates. You'll need to re-run parts of the build script in sequence until your certs are populated, e.g.

```
sudo docker compose -f docker-compose.gpu-prod.yml run --name onyx-stack --rm --build --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    -d ai-staging.mamamia.com.au \
    --rsa-key-size 4096 \
    --agree-tos \
    --force-renewal" certbot
```

#### Scorched Earth docker reset

If you need to start fresh, it's easiest to start with a new instance. If for some reason that won't work, here's how to remove all traces of Onyx:
- ssh into the instance (see below)
- run `sudo docker rm -vf $(sudo docker ps -aq) && sudo docker rmi -f $(sudo docker images -aq) && sudo docker volume prune -f -a && sudo docker builder prune -a -f`

## SSH access

You can always access the instance via SSH through the GCP console, but if you want to do it from your own terminal here's how:
- install the Google Cloud CLI
- run `gcloud compute config-ssh` to sync your local with SSH-accessible instances in GCP
- run `ssh <instance-uri>`, where `<instance-uri>` is something like `onyx-staging.us-central1-a.mamamia-pwa`

## Onyx Database

Onyx uses a Postgres database. It's often useful to view the DB directly - here's how to hook up your favourite Postgres client:
- install the Google Cloud CLI
- run `gcloud compute config-ssh` to sync your local with SSH-accessible instances in GCP
- run `ssh <instance-uri> "sudo docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' onyx-stack-relational_db-1", where `<instance-uri>` is something like `onyx-staging.us-central1-a.mamamia-pwa`
- the IP address returned is the database `host`
- `user=postgres`
- `password=password`
- Configure your DB client to use an SSH tunnel:
   - run `ssh -v <instance-uri> ' ' 2>&1 | grep '^debug1: Connecting to' to get the public external IP address of the instance (or you could get it from GCP)
   - use that IP as your SSH tunnel `host`
   - no need to set `user` or `password`, but make sure you use the private key at `~/.ssh/google_compute_engine` instead of your default one

