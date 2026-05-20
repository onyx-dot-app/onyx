#!/bin/bash
# Sandbox bootstrap: CA trust-store + iptables egress lockdown + self-verify.
#
# SANDBOX_PROXY_BOOTSTRAP_MODE selects:
#   initcontainer  — K8s initContainer; steps 1-4 then exit 0.
#   entrypoint     — docker-compose entrypoint; steps 1-4 then exec the
#                    real entrypoint as UID 1000 via gosu.
#
# All steps must be idempotent (initContainers may restart; entrypoint
# mode runs on every container start).
#
# Required env vars:
#   SANDBOX_PROXY_HOST              — proxy hostname or IP
#   SANDBOX_PROXY_PORT              — proxy TCP port
#   SANDBOX_PROXY_BOOTSTRAP_MODE    — "initcontainer" or "entrypoint"
#
# Optional env vars:
#   SANDBOX_PROXY_CA_BUNDLE_SRC     — default /sandbox-ca/ca.crt
#   SANDBOX_PROXY_CA_BUNDLE_DST     — default /etc/ssl/sandbox/ca-bundle.crt
#   SANDBOX_PROXY_VERIFY_TARGET     — default 1.1.1.1

set -euo pipefail

log() {
    echo "[firewall-init] $*" >&2
}

die() {
    log "FATAL: $*"
    exit 1
}

: "${SANDBOX_PROXY_HOST:?SANDBOX_PROXY_HOST not set}"
: "${SANDBOX_PROXY_PORT:?SANDBOX_PROXY_PORT not set}"
: "${SANDBOX_PROXY_BOOTSTRAP_MODE:?SANDBOX_PROXY_BOOTSTRAP_MODE not set}"

CA_SRC="${SANDBOX_PROXY_CA_BUNDLE_SRC:-/sandbox-ca/ca.crt}"
CA_DST="${SANDBOX_PROXY_CA_BUNDLE_DST:-/etc/ssl/sandbox/ca-bundle.crt}"
VERIFY_TARGET="${SANDBOX_PROXY_VERIFY_TARGET:-1.1.1.1}"

case "$SANDBOX_PROXY_BOOTSTRAP_MODE" in
    initcontainer|entrypoint)
        ;;
    *)
        die "unknown SANDBOX_PROXY_BOOTSTRAP_MODE=$SANDBOX_PROXY_BOOTSTRAP_MODE"
        ;;
esac

log "mode=$SANDBOX_PROXY_BOOTSTRAP_MODE proxy=$SANDBOX_PROXY_HOST:$SANDBOX_PROXY_PORT"


step_install_ca() {
    if [[ ! -f "$CA_SRC" ]]; then
        die "CA source $CA_SRC not present — is the CA ConfigMap mounted?"
    fi

    install -d -m 0755 /usr/local/share/ca-certificates
    install -m 0644 "$CA_SRC" /usr/local/share/ca-certificates/sandbox-proxy.crt

    if ! update-ca-certificates >/dev/null 2>&1; then
        die "update-ca-certificates failed; cannot trust proxy CA"
    fi

    # Copy (not symlink) so the main container can mount $CA_DST's
    # parent dir as an emptyDir-from-init.
    install -d -m 0755 "$(dirname "$CA_DST")"
    install -m 0644 /etc/ssl/certs/ca-certificates.crt "$CA_DST"

    log "installed proxy CA -> $CA_DST"
}


step_apply_iptables() {
    # Resolve once before lockdown is installed. K8s passes a
    # ClusterIP directly; docker uses an embedded DNS that's still
    # reachable at this point.
    local proxy_ip
    if [[ "$SANDBOX_PROXY_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        proxy_ip="$SANDBOX_PROXY_HOST"
    else
        proxy_ip="$(getent hosts "$SANDBOX_PROXY_HOST" | awk '{print $1; exit}')"
        if [[ -z "$proxy_ip" ]]; then
            die "could not resolve proxy host $SANDBOX_PROXY_HOST"
        fi
    fi
    log "resolved proxy ip=$proxy_ip"

    iptables -F OUTPUT
    iptables -P OUTPUT DROP
    iptables -P INPUT ACCEPT
    iptables -P FORWARD DROP

    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A OUTPUT -p tcp -d "$proxy_ip" --dport "$SANDBOX_PROXY_PORT" -j ACCEPT
    iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited

    if command -v ip6tables >/dev/null 2>&1; then
        ip6tables -F OUTPUT || true
        ip6tables -P OUTPUT DROP || true
    fi

    log "iptables egress lockdown installed (allow ${proxy_ip}:${SANDBOX_PROXY_PORT})"
}


step_pre_resolve_proxy() {
    # initcontainer: DNS gets blocked by step 2, so write the proxy IP
    # into /etc/hosts. entrypoint: docker's embedded DNS bypasses
    # iptables and resolves the compose service name fine.
    case "$SANDBOX_PROXY_BOOTSTRAP_MODE" in
        initcontainer)
            local proxy_ip
            if [[ "$SANDBOX_PROXY_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                proxy_ip="$SANDBOX_PROXY_HOST"
            else
                proxy_ip="$(getent hosts "$SANDBOX_PROXY_HOST" | awk '{print $1; exit}')"
            fi
            if ! grep -qE "^${proxy_ip//./\\.}[[:space:]]+sandbox-proxy" /etc/hosts; then
                echo "${proxy_ip} sandbox-proxy" >> /etc/hosts
            fi
            log "wrote sandbox-proxy -> ${proxy_ip} into /etc/hosts"
            ;;
        entrypoint)
            log "step 3 skipped in entrypoint mode"
            ;;
    esac
}


step_self_verify() {
    log "self-verify: probing ${VERIFY_TARGET}, expecting failure"
    if curl --silent --output /dev/null --max-time 2 "https://${VERIFY_TARGET}"; then
        die "self-verify probe SUCCEEDED — iptables lockdown not in effect"
    fi
    log "self-verify: probe failed as expected"
}


step_install_ca
step_apply_iptables
step_pre_resolve_proxy
step_self_verify


case "$SANDBOX_PROXY_BOOTSTRAP_MODE" in
    initcontainer)
        log "initcontainer mode: bootstrap complete, exiting 0"
        exit 0
        ;;
    entrypoint)
        # gosu does setuid() directly (no execve), so post-drop caps
        # remain the bounded set from the container's cap_add/cap_drop.
        if [[ "$#" -lt 1 ]]; then
            die "entrypoint mode requires the real entrypoint as args"
        fi
        log "entrypoint mode: dropping to UID 1000 and exec'ing: $*"
        exec gosu 1000:1000 "$@"
        ;;
esac
