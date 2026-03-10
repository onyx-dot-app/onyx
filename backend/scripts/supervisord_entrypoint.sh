#!/bin/sh
# Entrypoint script for supervisord

# Launch supervisord with environment variables available
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
