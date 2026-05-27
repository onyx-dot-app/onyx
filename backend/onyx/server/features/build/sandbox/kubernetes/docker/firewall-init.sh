#!/bin/bash
# Sandbox bootstrap: CA trust-store + iptables egress lockdown + self-verify.
#
# SANDBOX_PROXY_BOOTSTRAP_MODE:
#   initcontainer — K8s initContainer; runs steps then exits 0.
#   entrypoint    — docker-compose entrypoint; runs steps then execs the
#                   real entrypoint as UID 1000 via gosu.
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

# Resolved once in step_apply_iptables before the lockdown closes DNS,
# then reused in step_self_verify.
PROXY_IP=""

case "$SANDBOX_PROXY_BOOTSTRAP_MODE" in
    initcontainer|entrypoint) ;;
    *) die "unknown SANDBOX_PROXY_BOOTSTRAP_MODE=$SANDBOX_PROXY_BOOTSTRAP_MODE" ;;
esac

for bin in iptables ip6tables update-ca-certificates getent; do
    command -v "$bin" >/dev/null 2>&1 || die "required binary '$bin' missing"
done
if [[ "$SANDBOX_PROXY_BOOTSTRAP_MODE" == "entrypoint" ]] \
        && ! command -v gosu >/dev/null 2>&1; then
    die "entrypoint mode requires gosu; not found"
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
    if [[ "$SANDBOX_PROXY_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        PROXY_IP="$SANDBOX_PROXY_HOST"
    else
        PROXY_IP="$(getent hosts "$SANDBOX_PROXY_HOST" | awk '{print $1; exit}')"
        [[ -n "$PROXY_IP" ]] || die "could not resolve proxy host $SANDBOX_PROXY_HOST"
    fi
    log "resolved proxy ip=$PROXY_IP"

    iptables -F OUTPUT
    iptables -P OUTPUT DROP
    iptables -P INPUT ACCEPT
    iptables -P FORWARD DROP

    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A OUTPUT -p tcp -d "$PROXY_IP" --dport "$SANDBOX_PROXY_PORT" -j ACCEPT
    iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited

    # IPv6 lockdown is mandatory; partial lockdown = security regression.
    ip6tables -F OUTPUT
    ip6tables -P OUTPUT DROP

    log "iptables egress lockdown installed (allow ${PROXY_IP}:${SANDBOX_PROXY_PORT})"
}


# `sandbox-proxy` resolution after the lockdown comes from outside this
# script: pod hostAliases under K8s (kubelet won't propagate /etc/hosts
# writes across containers), Docker's embedded DNS under compose.


step_self_verify() {
    # Inspecting the chain (not probing the network): a network probe
    # can't distinguish "lockdown working" from "no internet" — fail-open.
    log "self-verify: inspecting iptables OUTPUT chain"
    local rules
    rules="$(iptables -S OUTPUT)"

    grep -qE "^-P OUTPUT DROP$" <<<"$rules" \
        || die "self-verify: OUTPUT default policy is not DROP"
    # iptables normalises single IPs to /32; accept the bare form too.
    grep -qE "^-A OUTPUT .*-d ${PROXY_IP//./\\.}(/32)?[[:space:]].*--dport ${SANDBOX_PROXY_PORT}[[:space:]].*-j ACCEPT$" <<<"$rules" \
        || die "self-verify: no ACCEPT rule for ${PROXY_IP}:${SANDBOX_PROXY_PORT}"
    grep -qE "^-A OUTPUT -m conntrack --ctstate (RELATED,ESTABLISHED|ESTABLISHED,RELATED) -j ACCEPT$" <<<"$rules" \
        || die "self-verify: no conntrack ESTABLISHED/RELATED rule"

    grep -qE "^-P OUTPUT DROP$" <(ip6tables -S OUTPUT) \
        || die "self-verify: ip6tables OUTPUT default policy is not DROP"

    log "self-verify: iptables OUTPUT chain looks correct"
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
        # gosu setuid()s directly (no execve), so post-drop caps remain
        # the bounded set from cap_add/cap_drop.
        [[ "$#" -ge 1 ]] || die "entrypoint mode requires the real entrypoint as args"
        log "entrypoint mode: dropping to UID 1000 and exec'ing: $*"
        exec gosu 1000:1000 "$@"
        ;;
esac
