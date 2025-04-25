#!/bin/bash

# This is test script for manually testing the Onyx Paperless-ngx connector.
# It sets up a test Paperless-ngx server using Docker, uploads test documents, and retrieves the auth token.
# It also cleans up the Docker containers and network after the test is completed.
# The script requires Docker and Curl to be installed on the system.
# Usage: ./run_test_paperless_server.sh

# Paperless-ngx credentials
USERNAME="admin"
PASSWORD="admin"

# change to your local IP address if necessary
HOST=$(ip addr | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1' | head -n 1) 
if [ -z "$HOST" ]; then
    HOST="localhost"
fi

PORT="8000"
PAPERLESS_URL_FOR_ONYX="http://$HOST:$PORT"

TEST_PDFS_URLS=(
    "https://raw.githubusercontent.com/py-pdf/sample-files/main/021-pdfa/crazyones-pdfa.pdf"
    "https://www.cte.iup.edu/cte/Resources/PDF_TestPage.pdf"
)
TEST_FILE_PREFIX="test_downloaded_document_"


if ! command -v docker &> /dev/null
then
    echo "Docker could not be found. Please install Docker to run this script."
    exit 1
fi

if ! command -v curl &> /dev/null
then
    echo "Curl could not be found. Please install Curl to run this script."
    exit 1
fi

cleanup() {
    echo "Cleaning up..."
    rm "$TEST_FILE_PREFIX"*.pdf > /dev/null 2>&1
    docker stop paperless-ngx-test paperless-test-redis > /dev/null 2>&1
    docker rm paperless-ngx-test paperless-test-redis > /dev/null 2>&1
    docker network rm paperless-test-network > /dev/null 2>&1
}

cleanup

# Set up trap to call cleanup on script exit
trap cleanup EXIT INT TERM

echo "Starting Paperless-ngx test server..."

# find a docker network that has "onyx" in the name and use it, otherwise create a new one
DOCKER_NETWORK=$(docker network ls --filter name=onyx --format "{{.Name}}")
if [ -z "$DOCKER_NETWORK" ]; then
    DOCKER_NETWORK="paperless-test-network"
    docker network create $DOCKER_NETWORK > /dev/null
else
    echo "Using existing Docker network '$DOCKER_NETWORK' for Onyx"
    PAPERLESS_URL_FOR_ONYX="http://paperless-ngx-test:8000"
fi


# start test Redis server 
docker run -d --name=paperless-test-redis --network $DOCKER_NETWORK redis:latest 1> /dev/null

# start the Paperless-ngx server 
docker run -d --name=paperless-ngx-test -e PUID=1000 -e PGID=1000  -e TZ=Etc/UTC -e PAPERLESS_SECRET_KEY=test -e PAPERLESS_URL=http://$HOST:$PORT -p $PORT:8000 --network $DOCKER_NETWORK -e PAPERLESS_ADMIN_USER=$USERNAME -e PAPERLESS_ADMIN_PASSWORD=$PASSWORD -e PAPERLESS_REDIS=redis://paperless-test-redis:6379 ghcr.io/paperless-ngx/paperless-ngx:latest 1> /dev/null


# wait for the server to start
time_between_checks=5 # seconds
max_attempts=20
timeout=$((time_between_checks * max_attempts))
attempts=0
while ! curl -s "http://$HOST:$PORT" > /dev/null; do
    ((attempts++))
    if [ $attempts -ge $max_attempts ]; then
        echo "Error: Paperless-ngx failed to start after $timeout seconds"
        exit 1
    fi
    echo -ne "\rWaiting for Paperless-ngx to start... ($((timeout - attempts * time_between_checks))s remaining)"
    sleep $time_between_checks
done
echo -ne "\nPaperless-ngx is up and running!\n\n"

# get the CSRF token in a cookies file
curl -s -u $USERNAME:$PASSWORD "http://$HOST:$PORT/api/schema/view/" -H "Content-Type: application/json" -c paperless-test-cookies.txt -o /dev/null 

# get the auth token and use the CSRF token from the cookies file
AUTH_TOKEN=$(curl -s -u $USERNAME:$PASSWORD -X POST "http://$HOST:$PORT/api/profile/generate_auth_token/" -H "Content-Type: application/json" -c paperless-test-cookies.txt | tr -d '"')
rm paperless-test-cookies.txt


if [ -z "$AUTH_TOKEN" ]; then
    echo "Error: Failed to retrieve auth token."
    exit 1
fi

# put test documents in paperless
doc_num=1
for url in "${TEST_PDFS_URLS[@]}"; do
    filename="${TEST_FILE_PREFIX}${doc_num}.pdf"
    curl -s -o "$filename" "$url"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to download test document from '$url'"
        exit 1
    fi
    curl -s -X POST "http://$HOST:$PORT/api/documents/post_document/" -H "Authorization: Token $AUTH_TOKEN" -F "document=@$filename" > /dev/null
    if [ $? -ne 0 ]; then
        echo "Error: Downloaded '$url', but failed to upload it to Paperless-ngx server."
        exit 1
    fi
    echo "Test document '$url' was uploaded to the Paperless-ngx server. You can view it at 'http://$HOST:$PORT/documents/$doc_num/preview' (use 'localhost' if on WSL)."
    ((doc_num++))
done
echo -e "\n\n"


echo "The Paperless-ngx server is running at http://$HOST:$PORT or http://localhost:$PORT with the following credentials:"
echo "  Onyx Paperless-ngx Connector url: $PAPERLESS_URL_FOR_ONYX"
echo "  Username: $USERNAME"
echo "  Password: $PASSWORD"
echo "  Auth token: $AUTH_TOKEN"

echo -e "\nYou can now test the Onyx Paperless-ngx connector with the above credentials in Onyx and it will index the uploaded documents.\n"
read -rsn1 -p "Press any key to end this test and clean up."; echo

exit 0
