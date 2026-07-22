#!/bin/bash

# DOMAIN (and optionally EMAIL) are read from the .env file in this
# directory (see env.prod.template). A legacy .env.nginx file is still
# honored as a fallback.
read_env_value() {
  grep -E "^$1=" "$2" 2>/dev/null | tail -n1 | cut -d= -f2-
}
DOMAIN="$(read_env_value DOMAIN .env)"
EMAIL="$(read_env_value EMAIL .env)"
if [[ -z "$DOMAIN" && -f .env.nginx ]]; then
  DOMAIN="$(read_env_value DOMAIN .env.nginx)"
  EMAIL="${EMAIL:-$(read_env_value EMAIL .env.nginx)}"
fi
if [[ -z "$DOMAIN" ]]; then
  echo "Error: DOMAIN must be set in .env (see env.prod.template)." >&2
  exit 1
fi

docker_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
  else
    echo 'Error: docker compose (V2 plugin) or docker-compose is not installed.' >&2
    exit 1
  fi
}

COMPOSE_CMD=$(docker_compose_cmd)

COMPOSE_FILES=(-f docker-compose.yml)

# --wait/--wait-timeout are V2-only.
WAIT_ARGS=(--wait --wait-timeout 300)
[[ "$COMPOSE_CMD" == "docker-compose" ]] && WAIT_ARGS=()

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
$COMPOSE_CMD "${COMPOSE_FILES[@]}" run  --name onyx --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1\
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot
echo


echo "### Starting nginx ..."
$COMPOSE_CMD "${COMPOSE_FILES[@]}" up --force-recreate -d "${WAIT_ARGS[@]}" nginx
echo

echo "### Deleting dummy certificate for $domains ..."
$COMPOSE_CMD "${COMPOSE_FILES[@]}" run  --name onyx --rm --entrypoint "\
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

$COMPOSE_CMD "${COMPOSE_FILES[@]}" run --name onyx --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $email_arg \
    $domain_args \
    --rsa-key-size $rsa_key_size \
    --agree-tos \
    --force-renewal" certbot
echo

echo "### Renaming certificate directory if needed ..."
$COMPOSE_CMD "${COMPOSE_FILES[@]}" run --name onyx --rm --entrypoint "\
  sh -c 'for domain in $domains; do \
    numbered_dir=\$(find /etc/letsencrypt/live -maxdepth 1 -type d -name \"\$domain-00*\" | sort -r | head -n1); \
    if [ -n \"\$numbered_dir\" ]; then \
      mv \"\$numbered_dir\" /etc/letsencrypt/live/\$domain; \
    fi; \
  done'" certbot

echo "### Reloading nginx ..."
$COMPOSE_CMD "${COMPOSE_FILES[@]}" up --force-recreate -d
