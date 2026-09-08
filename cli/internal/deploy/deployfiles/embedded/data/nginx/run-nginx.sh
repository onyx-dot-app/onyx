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

echo "Using API server host: $ONYX_BACKEND_API_HOST"
echo "Using web server host: $ONYX_WEB_SERVER_HOST"
echo "Using MCP server host: $ONYX_MCP_SERVER_HOST"
echo "Using nginx proxy timeouts - connect: ${NGINX_PROXY_CONNECT_TIMEOUT}s, send: ${NGINX_PROXY_SEND_TIMEOUT}s, read: ${NGINX_PROXY_READ_TIMEOUT}s"

# shellcheck disable=SC2016
envsubst '$DOMAIN $SSL_CERT_FILE_NAME $SSL_CERT_KEY_FILE_NAME $ONYX_BACKEND_API_HOST $ONYX_WEB_SERVER_HOST $ONYX_MCP_SERVER_HOST $NGINX_PROXY_CONNECT_TIMEOUT $NGINX_PROXY_SEND_TIMEOUT $NGINX_PROXY_READ_TIMEOUT' < "/etc/nginx/conf.d/$1" > /etc/nginx/conf.d/app.conf

# Conditionally create MCP server configuration
if [ "${MCP_SERVER_ENABLED}" = "True" ] || [ "${MCP_SERVER_ENABLED}" = "true" ]; then
  echo "MCP server is enabled, creating MCP configuration..."
  # shellcheck disable=SC2016
  envsubst '$ONYX_MCP_SERVER_HOST $ONYX_WEB_SERVER_HOST' < "/etc/nginx/conf.d/mcp.conf.inc.template" > /etc/nginx/conf.d/mcp.conf.inc
else
  echo "MCP server is disabled, removing MCP configuration..."
  # Leave an empty placeholder file so the nginx include does not fail
  echo "# Empty file - MCP server is disabled" > /etc/nginx/conf.d/mcp.conf.inc
fi
# app.conf templates from before upstream hosts were resolved per request
# include this file at http level; keep it so a hand-edited one still loads.
echo "# Empty file - upstream hosts are set per request in app.conf" > /etc/nginx/conf.d/mcp_upstream.conf.inc

# Start nginx and reload every 6 hours
while :; do sleep 6h & wait; nginx -s reload; done & nginx -g "daemon off;"
