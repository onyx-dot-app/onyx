#!/bin/sh
set -e
# fill in the template
export ONYX_BACKEND_API_HOST="${ONYX_BACKEND_API_HOST:-api_server}"
export ONYX_WEB_SERVER_HOST="${ONYX_WEB_SERVER_HOST:-web_server}"
export ONYX_MCP_SERVER_HOST="${ONYX_MCP_SERVER_HOST:-mcp_server}"

export SSL_CERT_FILE_NAME="${SSL_CERT_FILE_NAME:-ssl.crt}"
export SSL_CERT_KEY_FILE_NAME="${SSL_CERT_KEY_FILE_NAME:-ssl.key}"

# Nginx timeout settings (in seconds)
export NGINX_PROXY_CONNECT_TIMEOUT="${NGINX_PROXY_CONNECT_TIMEOUT:-300}"
export NGINX_PROXY_SEND_TIMEOUT="${NGINX_PROXY_SEND_TIMEOUT:-300}"
export NGINX_PROXY_READ_TIMEOUT="${NGINX_PROXY_READ_TIMEOUT:-300}"

echo "Using API server host: $ONYX_BACKEND_API_HOST"
echo "Using web server host: $ONYX_WEB_SERVER_HOST"
echo "Using MCP server host: $ONYX_MCP_SERVER_HOST"
echo "Using nginx proxy timeouts - connect: ${NGINX_PROXY_CONNECT_TIMEOUT}s, send: ${NGINX_PROXY_SEND_TIMEOUT}s, read: ${NGINX_PROXY_READ_TIMEOUT}s"

export CONF_DIR="${CONF_DIR:-/etc/nginx/conf.d}"

# shellcheck disable=SC2016
envsubst '$DOMAIN $CONF_DIR $SSL_CERT_FILE_NAME $SSL_CERT_KEY_FILE_NAME $ONYX_BACKEND_API_HOST $ONYX_WEB_SERVER_HOST $ONYX_MCP_SERVER_HOST $NGINX_PROXY_CONNECT_TIMEOUT $NGINX_PROXY_SEND_TIMEOUT $NGINX_PROXY_READ_TIMEOUT' < "$CONF_DIR/$1" > "$CONF_DIR/app.conf"

# Conditionally create MCP server configuration
if [ "${MCP_SERVER_ENABLED}" = "True" ] || [ "${MCP_SERVER_ENABLED}" = "true" ]; then
  if [ -f "$CONF_DIR/mcp_upstream.conf.inc.template" ] && [ -f "$CONF_DIR/mcp.conf.inc.template" ]; then
    echo "MCP server is enabled, creating MCP configuration..."
    # shellcheck disable=SC2016
    envsubst '$ONYX_MCP_SERVER_HOST' < "$CONF_DIR/mcp_upstream.conf.inc.template" > "$CONF_DIR/mcp_upstream.conf.inc"
    # shellcheck disable=SC2016
    envsubst '$ONYX_MCP_SERVER_HOST' < "$CONF_DIR/mcp.conf.inc.template" > "$CONF_DIR/mcp.conf.inc"
  else
    echo "WARNING: MCP server is enabled, but MCP configuration templates are missing in $CONF_DIR."
    echo "Writing empty placeholders so nginx starts safely..."
    echo "# Empty file - MCP server templates not found" > "$CONF_DIR/mcp_upstream.conf.inc"
    echo "# Empty file - MCP server templates not found" > "$CONF_DIR/mcp.conf.inc"
  fi
else
  echo "MCP server is disabled, removing MCP configuration..."
  # Leave empty placeholder files so nginx includes do not fail
  # These files are empty because MCP server is disabled
  echo "# Empty file - MCP server is disabled" > "$CONF_DIR/mcp_upstream.conf.inc"
  echo "# Empty file - MCP server is disabled" > "$CONF_DIR/mcp.conf.inc"
fi

# Ensure webhook configuration exists even if not mounted
if [ ! -f "$CONF_DIR/webhook.conf.inc" ]; then
  echo "# Empty file - webhook configuration not found" > "$CONF_DIR/webhook.conf.inc"
fi

# Verify required configuration files exist before proceeding
for f in "$CONF_DIR/app.conf" "$CONF_DIR/mcp_upstream.conf.inc" "$CONF_DIR/mcp.conf.inc" "$CONF_DIR/webhook.conf.inc"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: Required configuration file $f is missing" >&2
    exit 1
  fi
done

# Start background reload loop only when daemon reload is requested
if [ "${RUN_NGINX_DAEMON:-true}" = "true" ]; then
  while :; do sleep 6h & wait; nginx -s reload || echo "Warning: nginx reload failed" >&2; done &
fi

nginx -g "daemon off;"
