# Webhook server routes.
#
# The upstream host is a variable, not an `upstream` block: nginx resolves a
# literal one at startup and aborts when the service is absent, which it is
# whenever the `webhook` profile is off. A variable also disables nginx's URI
# rewriting, hence one location per path shape.

location = /webhook {
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

    proxy_connect_timeout 10s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;

    proxy_pass http://$webhook_upstream:8091$1;
}
