FROM alpine:3.20

RUN apk add --no-cache iptables ip6tables bash iproute2 bind-tools

COPY setup.sh /usr/local/bin/setup.sh
RUN chmod +x /usr/local/bin/setup.sh

ENTRYPOINT ["/usr/local/bin/setup.sh"]
