#!/bin/bash
# Entrypoint script for supervisord that sets environment variables
# for controlling which celery workers to start

# Default to lightweight mode if not set
if [ -z "$USE_LIGHTWEIGHT_BACKGROUND_WORKER" ]; then
    export USE_LIGHTWEIGHT_BACKGROUND_WORKER="true"
fi

# Set the complementary variable for supervisord
if [ "$USE_LIGHTWEIGHT_BACKGROUND_WORKER" = "true" ]; then
    export USE_SEPARATE_BACKGROUND_WORKERS="false"
else
    export USE_SEPARATE_BACKGROUND_WORKERS="true"
fi

echo "Worker mode configuration:"
echo "  USE_LIGHTWEIGHT_BACKGROUND_WORKER=$USE_LIGHTWEIGHT_BACKGROUND_WORKER"
echo "  USE_SEPARATE_BACKGROUND_WORKERS=$USE_SEPARATE_BACKGROUND_WORKERS"

# Launch supervisord with environment variables available
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
