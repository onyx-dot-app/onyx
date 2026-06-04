#!/usr/bin/env bash
# Installs egress rules in the workload's network namespace, then exits.
#
# Runs with CAP_NET_ADMIN; the workload container has none of NET_ADMIN, so
# what we set here is tamper-resistant from inside the sandbox.
#
# Rules (in order):
#   1. nat OUTPUT: DNAT TCP/80  -> proxy:8081
#   2. nat OUTPUT: DNAT TCP/443 -> proxy:8443
#   3. filter OUTPUT: ALLOW the DNAT'd flows (reply traffic to the proxy)
#   4. filter OUTPUT: ALLOW loopback
#   5. filter OUTPUT: REJECT all other TCP with tcp-reset
#   6. filter OUTPUT: REJECT all UDP except DNS (DNS must work for
#      hostname-based egress; QUIC/HTTP3 is rejected)
#   7. ip6tables: REJECT all IPv6 egress (IPv6 is also disabled via sysctl
#      in the sandbox compose config, this is the belt to that suspenders)

set -euo pipefail

PROXY_HTTP_PORT="${PROXY_HTTP_PORT:-8081}"
PROXY_HTTPS_PORT="${PROXY_HTTPS_PORT:-8443}"
READY_FILE=/state/ready

log() { echo "[iptables-init] $*"; }

# Compose passes PROXY_IP directly (static IP on the sandbox-transparent net).
# K8s passes PROXY_HOST (a Service DNS name) instead; resolve it once here so
# the iptables rules below get an IP literal.
if [[ -z "${PROXY_IP:-}" ]]; then
    if [[ -z "${PROXY_HOST:-}" ]]; then
        log "FATAL: neither PROXY_IP nor PROXY_HOST set"
        exit 1
    fi
    PROXY_IP="$(dig +short "${PROXY_HOST}" A | head -n1)"
    if [[ -z "$PROXY_IP" ]]; then
        log "FATAL: could not resolve PROXY_HOST=${PROXY_HOST}"
        exit 1
    fi
    log "resolved PROXY_HOST=${PROXY_HOST} -> PROXY_IP=${PROXY_IP}"
fi

log "configuring egress rules: proxy=${PROXY_IP} http=${PROXY_HTTP_PORT} https=${PROXY_HTTPS_PORT}"

# ---- Routing: link-scope default route via eth0 ----
# internal:true networks have no default route. Without one, the kernel's
# initial routing decision for non-bridge IPs (e.g. 198.51.100.1) returns
# "Network is unreachable" *before* nat/OUTPUT runs, so DNAT never fires.
# A link-scope default route lets the kernel proceed; DNAT then rewrites
# the destination to the proxy's bridge IP, which IS routable. Non-DNAT'd
# packets fall through to the REJECT rules below.
ip route add default dev eth0 2>/dev/null || \
    log "default route already present (or unable to add — see filter rules)"

# ---- IPv4 NAT: redirect HTTP/HTTPS to the proxy ----
# Two cases:
#   - PROXY_IP is a remote IP (compose: 172.30.0.10): plain DNAT.
#   - PROXY_IP is loopback (K8s sidecar: 127.0.0.1): use iptables REDIRECT.
#     REDIRECT in OUTPUT is a kernel-special form of DNAT that auto-rewrites
#     destination to 127.0.0.1 AND lets re-routing pick the lo interface
#     with src=127.0.0.1, dodging the martian-source check that plain DNAT
#     to a loopback dest would otherwise hit. (DNAT to 127.0.0.1 would need
#     net.ipv4.conf.*.route_localnet=1, which requires write access to
#     /proc/sys that non-privileged containers don't have.)
case "$PROXY_IP" in
    127.*)
        iptables -t nat -A OUTPUT -p tcp --dport 80  -j REDIRECT --to-ports "${PROXY_HTTP_PORT}"
        iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-ports "${PROXY_HTTPS_PORT}"
        ;;
    *)
        iptables -t nat -A OUTPUT -p tcp --dport 80  -j DNAT --to-destination "${PROXY_IP}:${PROXY_HTTP_PORT}"
        iptables -t nat -A OUTPUT -p tcp --dport 443 -j DNAT --to-destination "${PROXY_IP}:${PROXY_HTTPS_PORT}"
        ;;
esac

# ---- IPv4 filter: deny everything else, with narrow allows ----
# Sidecar-mode allow: traffic owned by the proxy's UID escapes the egress
# fence entirely. This is the only way to distinguish the proxy sidecar
# from the workload when both share the pod netns. Istio uses the same
# pattern. PROXY_UID is read from env (default 1337). No-op when unset.
if [[ -n "${PROXY_UID:-}" ]]; then
    iptables -A OUTPUT -m owner --uid-owner "${PROXY_UID}" -j ACCEPT
    log "allowed all egress for uid=${PROXY_UID} (proxy sidecar)"
fi
# Allow return traffic for any conntrack-established flow (so the proxy
# sidecar's replies to incoming probes / sandbox-initiated requests can
# leave the pod). Without this, the catch-all REJECT below would tcp-reset
# every SYN-ACK the proxy tries to send back to a remote client.
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# Allow loopback so local sockets keep working.
iptables -A OUTPUT -o lo -j ACCEPT
# Allow the redirected flows to actually reach the proxy.
iptables -A OUTPUT -p tcp -d "${PROXY_IP}" --dport "${PROXY_HTTP_PORT}"  -j ACCEPT
iptables -A OUTPUT -p tcp -d "${PROXY_IP}" --dport "${PROXY_HTTPS_PORT}" -j ACCEPT
# Allow DNS so the workload can resolve hostnames (DNAT happens after
# resolution; the resolved IP is irrelevant since DNAT rewrites the dest).
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
# Reject everything else, loudly (tcp-reset so attempts fail fast).
iptables -A OUTPUT -p tcp -j REJECT --reject-with tcp-reset
iptables -A OUTPUT -p udp -j REJECT --reject-with icmp-port-unreachable
iptables -A OUTPUT -j REJECT --reject-with icmp-net-unreachable

# ---- IPv6: block entirely ----
ip6tables -P OUTPUT DROP || true
ip6tables -A OUTPUT -o lo -j ACCEPT || true
ip6tables -A OUTPUT -j REJECT || true

log "rules installed; current OUTPUT (nat):"
iptables -t nat -L OUTPUT -n --line-numbers || true
log "rules installed; current OUTPUT (filter):"
iptables -L OUTPUT -n --line-numbers || true

# Signal readiness so the workload entrypoint can take over.
mkdir -p "$(dirname "$READY_FILE")"
echo "ready=$(date -u +%FT%TZ)" > "$READY_FILE"

log "ready file written at $READY_FILE; exiting"
