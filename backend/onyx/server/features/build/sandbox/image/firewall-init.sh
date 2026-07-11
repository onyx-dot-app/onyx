#!/bin/bash
# Sandbox bootstrap: CA trust-store + iptables egress lockdown + self-verify.
#
# SANDBOX_PROXY_BOOTSTRAP_MODE:
#   initcontainer — K8s initContainer; runs steps then exits 0.
#   entrypoint    — docker-compose entrypoint; runs steps then execs the real
#                   entrypoint as UID 1000 via setpriv.
#
# Required env: SANDBOX_PROXY_HOST, SANDBOX_PROXY_PORT, SANDBOX_PROXY_BOOTSTRAP_MODE.
# Optional env: SANDBOX_PROXY_CA_BUNDLE_SRC (default /sandbox-ca/ca.crt),
#               SANDBOX_PROXY_CA_BUNDLE_DST (default /etc/ssl/sandbox/ca-bundle.crt).

set -euo pipefail

log() { echo "[firewall-init] $*" >&2; }
die() { log "FATAL: $*"; exit 1; }

: "${SANDBOX_PROXY_HOST:?SANDBOX_PROXY_HOST not set}"
: "${SANDBOX_PROXY_PORT:?SANDBOX_PROXY_PORT not set}"
: "${SANDBOX_PROXY_BOOTSTRAP_MODE:?SANDBOX_PROXY_BOOTSTRAP_MODE not set}"

CA_SRC="${SANDBOX_PROXY_CA_BUNDLE_SRC:-/sandbox-ca/ca.crt}"
CA_DST="${SANDBOX_PROXY_CA_BUNDLE_DST:-/etc/ssl/sandbox/ca-bundle.crt}"

# Resolved once in step_apply_iptables before the lockdown closes DNS, then
# reused in step_self_verify. FAMILY is "inet" (IPv4) or "inet6" (IPv6) — the
# proxy's address family, which decides whether the allow rule goes in iptables
# or ip6tables (IPv6-only clusters give the proxy Service an IPv6 ClusterIP).
PROXY_IP=""
FAMILY=""

case "$SANDBOX_PROXY_BOOTSTRAP_MODE" in
    initcontainer|entrypoint) ;;
    *) die "unknown SANDBOX_PROXY_BOOTSTRAP_MODE=$SANDBOX_PROXY_BOOTSTRAP_MODE" ;;
esac

for bin in iptables ip6tables update-ca-certificates getent; do
    command -v "$bin" >/dev/null 2>&1 || die "required binary '$bin' missing"
done
if [[ "$SANDBOX_PROXY_BOOTSTRAP_MODE" == "entrypoint" ]] \
        && ! command -v setpriv >/dev/null 2>&1; then
    die "entrypoint mode requires setpriv (util-linux); not found"
fi

log "mode=$SANDBOX_PROXY_BOOTSTRAP_MODE proxy=$SANDBOX_PROXY_HOST:$SANDBOX_PROXY_PORT"


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
    # Resolve the proxy to a single IP and note its family. IPv6-only clusters
    # give the proxy Service an IPv6 ClusterIP, so an IPv4-only lookup returns
    # nothing — try v4 then v6. The getent calls live in the `elif` conditions
    # so a not-found (exit 2) doesn't trip `set -e` mid-resolution.
    if [[ "$SANDBOX_PROXY_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        PROXY_IP="$SANDBOX_PROXY_HOST"; FAMILY="inet"
    elif [[ "$SANDBOX_PROXY_HOST" == *:* ]]; then
        PROXY_IP="$SANDBOX_PROXY_HOST"; FAMILY="inet6"
    elif PROXY_IP="$(getent ahostsv4 "$SANDBOX_PROXY_HOST" | awk '{print $1; exit}')" \
            && [[ -n "$PROXY_IP" ]]; then
        FAMILY="inet"
    elif PROXY_IP="$(getent ahostsv6 "$SANDBOX_PROXY_HOST" | awk '{print $1; exit}')" \
            && [[ -n "$PROXY_IP" ]]; then
        FAMILY="inet6"
    else
        die "could not resolve proxy host $SANDBOX_PROXY_HOST to an IPv4 or IPv6 address"
    fi
    log "resolved proxy ip=$PROXY_IP family=$FAMILY"

    # Default-DROP egress on BOTH families; the unused family stays fully closed.
    local ipt
    for ipt in iptables ip6tables; do
        "$ipt" -F OUTPUT
        "$ipt" -P OUTPUT DROP
        "$ipt" -P INPUT ACCEPT
        "$ipt" -P FORWARD DROP
        "$ipt" -A OUTPUT -o lo -j ACCEPT
        "$ipt" -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    done

    # Allow only the proxy, on its own family.
    if [[ "$FAMILY" == "inet" ]]; then
        iptables -A OUTPUT -p tcp -d "$PROXY_IP" --dport "$SANDBOX_PROXY_PORT" -j ACCEPT
    else
        ip6tables -A OUTPUT -p tcp -d "$PROXY_IP" --dport "$SANDBOX_PROXY_PORT" -j ACCEPT
    fi

    iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited
    ip6tables -A OUTPUT -j REJECT --reject-with icmp6-adm-prohibited

    log "iptables egress lockdown installed (allow ${PROXY_IP}:${SANDBOX_PROXY_PORT} on ${FAMILY})"
}


# `sandbox-proxy` resolution after the lockdown comes from outside this script:
# pod hostAliases under K8s (kubelet won't propagate /etc/hosts writes across
# containers), Docker's embedded DNS under compose.


step_self_verify() {
    # Inspecting the chain (not probing the network): a network probe can't
    # distinguish "lockdown working" from "no internet" — fail-open.
    log "self-verify: inspecting iptables OUTPUT chains"

    # Both families must default-DROP egress; partial lockdown = regression.
    grep -qE "^-P OUTPUT DROP$" <(iptables -S OUTPUT) \
        || die "self-verify: iptables OUTPUT default policy is not DROP"
    grep -qE "^-P OUTPUT DROP$" <(ip6tables -S OUTPUT) \
        || die "self-verify: ip6tables OUTPUT default policy is not DROP"

    # The proxy ACCEPT + conntrack rules live on the proxy's family chain.
    local ipt="iptables"
    [[ "$FAMILY" == "inet6" ]] && ipt="ip6tables"
    local rules
    rules="$("$ipt" -S OUTPUT)"

    if [[ "$FAMILY" == "inet" ]]; then
        # iptables normalises single IPs to /32; accept the bare form too.
        grep -qE -- "^-A OUTPUT .*-d ${PROXY_IP//./\\.}(/32)?[[:space:]].*--dport ${SANDBOX_PROXY_PORT}[[:space:]].*-j ACCEPT$" <<<"$rules" \
            || die "self-verify: no ACCEPT rule for ${PROXY_IP}:${SANDBOX_PROXY_PORT}"
    else
        # ip6tables normalises IPv6 addresses (compression/expansion), so match
        # on the port + ACCEPT — there is only one allow rule.
        grep -qE -- "--dport ${SANDBOX_PROXY_PORT}[[:space:]].*-j ACCEPT$" <<<"$rules" \
            || die "self-verify: no ACCEPT rule for the proxy port ${SANDBOX_PROXY_PORT} on ${FAMILY}"
    fi
    grep -qE "^-A OUTPUT -m conntrack --ctstate (RELATED,ESTABLISHED|ESTABLISHED,RELATED) -j ACCEPT$" <<<"$rules" \
        || die "self-verify: no conntrack ESTABLISHED/RELATED rule on ${FAMILY}"

    log "self-verify: iptables OUTPUT chains look correct"
}


step_install_ca
step_apply_iptables
step_self_verify


case "$SANDBOX_PROXY_BOOTSTRAP_MODE" in
    initcontainer)
        log "initcontainer mode: bootstrap complete, exiting 0"
        exit 0
        ;;
    entrypoint)
        # Compose-only: K8s initcontainer mode exits earlier, never reaches
        # here. Docker manager grants cap_add=[NET_ADMIN, SETPCAP, SETUID,
        # SETGID, CHOWN]: NET_ADMIN for iptables, SETPCAP for the bounding-set
        # drop, SETUID/SETGID for setpriv's --reuid/--regid under
        # cap_drop=ALL, and CHOWN for the sessions mount-point repair below.
        # setpriv (not capsh): capsh's `-- args` form invokes /bin/bash and
        # mangles non-script targets; setpriv execve's directly.
        [[ "$#" -ge 1 ]] || die "entrypoint mode requires the real entrypoint as args"

        # Fix volume mount permissions: Docker volumes are created with default
        # ownership (root:root). The Dockerfile's chown only affects the image
        # layer, not mounted volumes. Fix only the mount point before dropping
        # to UID 1000 so the sandbox user can create sessions without walking
        # existing saved workspaces on every container restart.
        if [ -d /workspace/sessions ]; then
            chown 1000:1000 /workspace/sessions
            log "fixed /workspace/sessions ownership -> 1000:1000"
        else
            log "WARNING: /workspace/sessions not found; session creation will fail"
        fi

        log "entrypoint mode: clearing bounding set, dropping to UID 1000, exec'ing: $*"
        # HOME/USER must be set explicitly: setpriv switches uid/gid but does
        # not refresh env vars. Inheriting HOME=/root from the root parent
        # leaves the dropped-to-1000 agent unable to write its caches
        # (opencode-serve dies at startup on EACCES /root/.cache).
        HOME=/home/sandbox USER=sandbox \
            exec setpriv --reuid=1000 --regid=1000 --init-groups \
            --bounding-set=-all -- "$@"
        ;;
esac
