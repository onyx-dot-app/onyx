#!/bin/bash

# .env.nginx file must be present in the same directory as this script and
# must set DOMAIN (and optionally EMAIL)
set -o allexport
source .env.nginx
set +o allexport

# Function to determine correct docker compose command
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

# Assign appropriate Docker Compose command
COMPOSE_CMD=$(docker_compose_cmd)

# Only add www to domain list if domain wasn't explicitly set as a subdomain
if [[ ! $DOMAIN == www.* ]]; then
    domains=("$DOMAIN" "www.$DOMAIN")
else
    domains=("$DOMAIN")
fi

rsa_key_size=4096
data_path="../data/certbot"
email="$EMAIL" # Adding a valid address is strongly recommended
staging=0 # Set to 1 if you're testing your setup to avoid hitting request limits

if [ -d "$data_path" ]; then
  read -p "Existing data found for $domains. Continue and replace existing certificate? (y/N) " decision
  if [ "$decision" != "Y" ] && [ "$decision" != "y" ]; then
    exit
  fi
fi


if [ ! -e "$data_path/conf/options-ssl-nginx.conf" ] || [ ! -e "$data_path/conf/ssl-dhparams.pem" ]; then
  echo "### Downloading recommended TLS parameters ..."
  mkdir -p "$data_path/conf"
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$data_path/conf/options-ssl-nginx.conf"
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > "$data_path/conf/ssl-dhparams.pem"
  echo
fi

echo "### Creating dummy certificate for $domains ..."
path="/etc/letsencrypt/live/$domains"
mkdir -p "$data_path/conf/live/$domains"
$COMPOSE_CMD -f docker-compose.prod.yml run  --name onyx --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1\
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot
echo


echo "### Starting nginx ..."
$COMPOSE_CMD -f docker-compose.prod.yml up --force-recreate -d nginx
echo

echo "Waiting for nginx to be ready, this may take a minute..."
while true; do
  # Use curl to send a request and capture the HTTP status code
  status_code=$(curl -o /dev/null -s -w "%{http_code}\n" "http://localhost/api/health")
  
  # Check if the status code is 200
  if [ "$status_code" -eq 200 ]; then
    break  # Exit the loop
  else
    echo "Nginx is not ready yet, retrying in 5 seconds..."
    sleep 5  # Sleep for 5 seconds before retrying
  fi
done

echo "### Deleting dummy certificate for $domains ..."
$COMPOSE_CMD -f docker-compose.prod.yml run  --name onyx --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$domains && \
  rm -Rf /etc/letsencrypt/archive/$domains && \
  rm -Rf /etc/letsencrypt/renewal/$domains.conf" certbot
echo


echo "### Requesting Let's Encrypt certificate for $domains ..."
#Join $domains to -d args
domain_args=""
for domain in "${domains[@]}"; do
  domain_args="$domain_args -d $domain"
done

# Select appropriate email arg
case "$email" in
  "") email_arg="--register-unsafely-without-email" ;;
  *) email_arg="--email $email" ;;
esac

# Enable staging mode if needed
if [ $staging != "0" ]; then staging_arg="--staging"; fi

$COMPOSE_CMD -f docker-compose.prod.yml run --name onyx --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $email_arg \
    $domain_args \
    --rsa-key-size $rsa_key_size \
    --agree-tos \
    --force-renewal" certbot
echo

echo "### Renaming certificate directory if needed ..."
$COMPOSE_CMD -f docker-compose.prod.yml run --name onyx --rm --entrypoint "\
  sh -c 'for domain in $domains; do \
    numbered_dir=\$(find /etc/letsencrypt/live -maxdepth 1 -type d -name \"\$domain-00*\" | sort -r | head -n1); \
    if [ -n \"\$numbered_dir\" ]; then \
      mv \"\$numbered_dir\" /etc/letsencrypt/live/\$domain; \
    fi; \
  done'" certbot

echo "### Reloading nginx ..."
$COMPOSE_CMD -f docker-compose.prod.yml up --force-recreate -d
