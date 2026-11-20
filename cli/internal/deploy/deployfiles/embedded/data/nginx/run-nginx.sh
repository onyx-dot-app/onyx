#!/bin/sh
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

# The prod templates redirect plain-HTTP requests to HTTPS unless this is false.
if [ "${NGINX_HTTPS_REDIRECT_ENABLED}" = "False" ] || [ "${NGINX_HTTPS_REDIRECT_ENABLED}" = "false" ]; then
  export NGINX_HTTPS_REDIRECT=0
else
  export NGINX_HTTPS_REDIRECT=1
fi

echo "Using API server host: $ONYX_BACKEND_API_HOST"
echo "Using web server host: $ONYX_WEB_SERVER_HOST"
echo "Using MCP server host: $ONYX_MCP_SERVER_HOST"
echo "Using nginx proxy timeouts - connect: ${NGINX_PROXY_CONNECT_TIMEOUT}s, send: ${NGINX_PROXY_SEND_TIMEOUT}s, read: ${NGINX_PROXY_READ_TIMEOUT}s"

# shellcheck disable=SC2016
envsubst '$DOMAIN $SSL_CERT_FILE_NAME $SSL_CERT_KEY_FILE_NAME $ONYX_BACKEND_API_HOST $ONYX_WEB_SERVER_HOST $ONYX_MCP_SERVER_HOST $NGINX_PROXY_CONNECT_TIMEOUT $NGINX_PROXY_SEND_TIMEOUT $NGINX_PROXY_READ_TIMEOUT $NGINX_HTTPS_REDIRECT' < "/etc/nginx/conf.d/$1" > /etc/nginx/conf.d/app.conf

# Conditionally create MCP server configuration
if [ "${MCP_SERVER_ENABLED}" = "True" ] || [ "${MCP_SERVER_ENABLED}" = "true" ]; then
  if [ -f /etc/nginx/conf.d/mcp_upstream.conf.inc.template ] && [ -f /etc/nginx/conf.d/mcp.conf.inc.template ]; then
    echo "MCP server is enabled, creating MCP configuration..."
    # shellcheck disable=SC2016
    envsubst '$ONYX_MCP_SERVER_HOST' < "/etc/nginx/conf.d/mcp_upstream.conf.inc.template" > /etc/nginx/conf.d/mcp_upstream.conf.inc
    # shellcheck disable=SC2016
    envsubst '$ONYX_MCP_SERVER_HOST' < "/etc/nginx/conf.d/mcp.conf.inc.template" > /etc/nginx/conf.d/mcp.conf.inc
  else
    echo "WARNING: MCP server is enabled, but the MCP nginx templates are missing. Starting nginx without the MCP routes."
    echo "# Empty file - MCP templates are missing" > /etc/nginx/conf.d/mcp_upstream.conf.inc
    echo "# Empty file - MCP templates are missing" > /etc/nginx/conf.d/mcp.conf.inc
  fi
else
  echo "MCP server is disabled, removing MCP configuration..."
  # Leave empty placeholder files so nginx includes do not fail
  # These files are empty because MCP server is disabled
  echo "# Empty file - MCP server is disabled" > /etc/nginx/conf.d/mcp_upstream.conf.inc
  echo "# Empty file - MCP server is disabled" > /etc/nginx/conf.d/mcp.conf.inc
fi

if [ ! -f /etc/nginx/conf.d/webhook.conf.inc ]; then
  echo "WARNING: webhook.conf.inc is missing. Starting nginx without the webhook routes."
  echo "# Empty file - webhook.conf.inc is missing" > /etc/nginx/conf.d/webhook.conf.inc
fi

# Start nginx and reload every 6 hours
while :; do sleep 6h & wait; nginx -s reload; done & nginx -g "daemon off;"
