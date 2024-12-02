#!/bin/bash

# Load environment variables
set -o allexport
source .env.nginx
set +o allexport

# Determine Docker Compose command
docker_compose_cmd() {
  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
  elif command -v docker compose >/dev/null 2>&1; then
    echo "docker compose"
  else
    echo 'Error: docker-compose or docker compose is not installed.' >&2
    exit 1
  fi
}

COMPOSE_CMD=$(docker_compose_cmd)

# Define domains and paths
if [[ ! $DOMAIN == www.* ]]; then
    domains=("$DOMAIN" "www.$DOMAIN")
else
    domains=("$DOMAIN")
fi
data_path="../data/certbot"

# Debugging: Print the resolved path
echo "Resolved data path: $data_path/conf/live/$DOMAIN"

# Ensure the certificates exist locally and resolve symlinks
real_cert_path=$(readlink -f "$data_path/conf/live/$DOMAIN/privkey.pem")
real_chain_path=$(readlink -f "$data_path/conf/live/$DOMAIN/fullchain.pem")

if [ ! -e "$real_cert_path" ] || [ ! -e "$real_chain_path" ]; then
  echo "Error: Resolved certificate files not found:"
  echo "Resolved privkey.pem: $real_cert_path"
  echo "Resolved fullchain.pem: $real_chain_path"
  exit 1
fi

echo "Resolved privkey.pem: $real_cert_path"
echo "Resolved fullchain.pem: $real_chain_path"

# Start the Nginx container with the correct volume mounts
echo "### Starting nginx with updated certificates ..."
$COMPOSE_CMD -f docker-compose.gpu-prod.yml -p danswer-stack up --force-recreate -d nginx

# Copy resolved certificate files into the container
echo "### Ensuring certificates are copied into the container ..."
container_id=$($COMPOSE_CMD -f docker-compose.gpu-prod.yml ps -q nginx)

docker cp "$real_cert_path" \
  "$container_id:/etc/letsencrypt/live/$DOMAIN/privkey.pem"

docker cp "$real_chain_path" \
  "$container_id:/etc/letsencrypt/live/$DOMAIN/fullchain.pem"

echo "### Certificates copied. Reloading nginx ..."
$COMPOSE_CMD -f docker-compose.gpu-prod.yml -p danswer-stack exec nginx nginx -s reload

echo "### Setup complete. Verify the site at https://$DOMAIN"
