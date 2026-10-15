#!/bin/bash
# Sandbox bootstrap: CA trust-store + iptables egress lockdown + self-verify.
#
# Firewall mode runs in the init container. CA mode runs in the root supervisor.
# Required env: SANDBOX_PROXY_HOST, SANDBOX_PROXY_PORT.
# Optional env: SANDBOX_PROXY_CA_BUNDLE_SRC (default /sandbox-ca/ca.crt),
#               SANDBOX_PROXY_CA_BUNDLE_DST (default /etc/ssl/sandbox/ca-bundle.crt).

set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

log() { echo "[firewall-init] $*" >&2; }
die() { log "FATAL: $*"; exit 1; }

: "${SANDBOX_PROXY_HOST:?SANDBOX_PROXY_HOST not set}"
: "${SANDBOX_PROXY_PORT:?SANDBOX_PROXY_PORT not set}"

CA_SRC="${SANDBOX_PROXY_CA_BUNDLE_SRC:-/sandbox-ca/ca.crt}"
CA_DST="${SANDBOX_PROXY_CA_BUNDLE_DST:-/etc/ssl/sandbox/ca-bundle.crt}"

# Resolved once in step_apply_iptables before the lockdown closes DNS, then
# reused in step_self_verify.
PROXY_IP=""
PROXY_TABLE="iptables"

for bin in iptables ip6tables update-ca-certificates getent; do
    command -v "$bin" >/dev/null 2>&1 || die "required binary '$bin' missing"
done
log "proxy=$SANDBOX_PROXY_HOST:$SANDBOX_PROXY_PORT"


step_install_ca() {
    [[ -f "$CA_SRC" ]] || die "CA source $CA_SRC not present"

    install -d -m 0755 /usr/local/share/ca-certificates
    install -m 0644 "$CA_SRC" /usr/local/share/ca-certificates/sandbox-proxy.crt

    update-ca-certificates >/dev/null 2>&1 \
        || die "update-ca-certificates failed"

    install -d -m 0755 "$(dirname "$CA_DST")"
    install -m 0644 /etc/ssl/certs/ca-certificates.crt "$CA_DST"

    log "installed proxy CA -> $CA_DST"
}


step_apply_iptables() {
    if [[ "$SANDBOX_PROXY_HOST" == *:* ]] \
            || [[ "$SANDBOX_PROXY_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        PROXY_IP="$SANDBOX_PROXY_HOST"
    else
        # Prefer IPv4 for existing deployments. `hosts` also resolves AAAA
        # records without AI_ADDRCONFIG excluding IPv6 in an initContainer.
        PROXY_IP="$(getent ahostsv4 "$SANDBOX_PROXY_HOST" | awk 'NR == 1 {print $1}' || true)"
        if [[ -z "$PROXY_IP" ]]; then
            PROXY_IP="$(getent hosts "$SANDBOX_PROXY_HOST" | awk '/:/ && !found {print $1; found=1}' || true)"
        fi
        [[ -n "$PROXY_IP" ]] || die "could not resolve proxy host $SANDBOX_PROXY_HOST"
    fi
    if [[ "$PROXY_IP" == *:* ]]; then
        PROXY_TABLE="ip6tables"
    fi
    log "resolved proxy ip=$PROXY_IP table=$PROXY_TABLE"

    # Both families stay locked down, including the unused family.
    local table
    for table in iptables ip6tables; do
        "$table" -F OUTPUT
        "$table" -P OUTPUT DROP
        "$table" -P INPUT ACCEPT
        "$table" -P FORWARD DROP
        "$table" -A OUTPUT -o lo -j ACCEPT
        "$table" -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    done

    # Neighbor discovery must work before the first allowed TCP connection.
    # Hop limit 255 restricts these messages to the directly attached link.
    for icmp_type in 135 136; do
        ip6tables -A OUTPUT -p ipv6-icmp --icmpv6-type "$icmp_type" \
            -m hl --hl-eq 255 -j ACCEPT
    done
    "$PROXY_TABLE" -A OUTPUT -p tcp -d "$PROXY_IP" --dport "$SANDBOX_PROXY_PORT" -j ACCEPT
    iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited
    ip6tables -A OUTPUT -j REJECT --reject-with icmp6-adm-prohibited

    log "egress lockdown installed (allow ${PROXY_IP}:${SANDBOX_PROXY_PORT})"
}


# Kubernetes supplies the proxy's pinned address through hostAliases.


step_self_verify() {
    # Inspect rules instead of relying on internet availability.
    local table icmp_type
    for table in iptables ip6tables; do
        "$table" -S OUTPUT | grep -qE "^-P OUTPUT DROP$" \
            || die "self-verify: $table OUTPUT default policy is not DROP"
        "$table" -C OUTPUT -o lo -j ACCEPT \
            || die "self-verify: $table loopback rule missing"
        "$table" -C OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT \
            || die "self-verify: $table conntrack rule missing"
    done
    "$PROXY_TABLE" -C OUTPUT -p tcp -d "$PROXY_IP" --dport "$SANDBOX_PROXY_PORT" -j ACCEPT \
        || die "self-verify: proxy ACCEPT rule missing"
    for icmp_type in 135 136; do
        ip6tables -C OUTPUT -p ipv6-icmp --icmpv6-type "$icmp_type" \
            -m hl --hl-eq 255 -j ACCEPT \
            || die "self-verify: neighbor discovery rule missing"
    done
    log "self-verify: both OUTPUT chains look correct"
}


case "${1:-}" in
    firewall)
        step_apply_iptables
        step_self_verify
        ;;
    ca)
        step_install_ca
        ;;
    *) die "expected firewall or ca mode" ;;
esac
