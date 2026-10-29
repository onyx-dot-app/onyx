# Webhook server - receives connector events from sources that push them.
#
# The service only exists when the `webhook` Compose profile is active, so
# this file must not stop nginx starting without it. A literal upstream would:
# nginx resolves those at startup and aborts on "host not found". Naming the
# host in a variable defers the lookup to request time, so nginx starts either
# way and answers 502 while the service is absent.
#
# A variable in proxy_pass also turns off nginx's automatic URI rewriting, so
# each location passes the path it wants explicitly. Hence two locations: the
# bare prefix maps to "/", and everything below it keeps its own path.

location = /webhook {
    resolver 127.0.0.11 valid=10s ipv6=off;  # Docker's embedded DNS
    set $webhook_upstream webhook_server;

    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_set_header Host $http_host;
    proxy_http_version 1.1;
    proxy_redirect off;

    proxy_pass http://$webhook_upstream:8091/;
}

location ~ ^/webhook(/.*)$ {
    resolver 127.0.0.11 valid=10s ipv6=off;
    set $webhook_upstream webhook_server;

    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_set_header Host $http_host;
    proxy_http_version 1.1;
    proxy_redirect off;

    # A provider retries on a slow answer, so keep these short.
    proxy_connect_timeout 10s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;

    proxy_pass http://$webhook_upstream:8091$1;
}
