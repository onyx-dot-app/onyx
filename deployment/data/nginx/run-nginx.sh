# fill in the template
export ONYX_BACKEND_API_HOST="${ONYX_BACKEND_API_HOST:-api_server}"
export ONYX_WEB_SERVER_HOST="${ONYX_WEB_SERVER_HOST:-web_server}"

export SSL_CERT_FILE_NAME="${SSL_CERT_FILE_NAME:-ssl.crt}"
export SSL_CERT_KEY_FILE_NAME="${SSL_CERT_KEY_FILE_NAME:-ssl.key}"

# Nginx timeout settings (in seconds)
export NGINX_PROXY_CONNECT_TIMEOUT="${NGINX_PROXY_CONNECT_TIMEOUT:-300}"
export NGINX_PROXY_SEND_TIMEOUT="${NGINX_PROXY_SEND_TIMEOUT:-300}"
export NGINX_PROXY_READ_TIMEOUT="${NGINX_PROXY_READ_TIMEOUT:-300}"

echo "Using API server host: $ONYX_BACKEND_API_HOST"
echo "Using web server host: $ONYX_WEB_SERVER_HOST"
echo "Using nginx proxy timeouts - connect: ${NGINX_PROXY_CONNECT_TIMEOUT}s, send: ${NGINX_PROXY_SEND_TIMEOUT}s, read: ${NGINX_PROXY_READ_TIMEOUT}s"

envsubst '$DOMAIN $SSL_CERT_FILE_NAME $SSL_CERT_KEY_FILE_NAME $ONYX_BACKEND_API_HOST $ONYX_WEB_SERVER_HOST $NGINX_PROXY_CONNECT_TIMEOUT $NGINX_PROXY_SEND_TIMEOUT $NGINX_PROXY_READ_TIMEOUT' < "/etc/nginx/conf.d/$1" > /etc/nginx/conf.d/app.conf

# wait for the api_server to be ready
echo "Waiting for API server to boot up; this may take a minute or two..."
echo "If this takes more than ~5 minutes, check the logs of the API server container for errors with the following command:"
echo
echo "docker logs onyx-api_server-1"
echo

while true; do
  # Use curl to send a request and capture the HTTP status code
  status_code=$(curl -o /dev/null -s -w "%{http_code}\n" "http://${ONYX_BACKEND_API_HOST}:8080/health")
  
  # Check if the status code is 200
  if [ "$status_code" -eq 200 ]; then
    echo "API server responded with 200, starting nginx..."
    break  # Exit the loop
  else
    echo "API server responded with $status_code, retrying in 5 seconds..."
    sleep 5  # Sleep for 5 seconds before retrying
  fi
done

# Start nginx and reload every 6 hours
while :; do sleep 6h & wait; nginx -s reload; done & nginx -g "daemon off;"
