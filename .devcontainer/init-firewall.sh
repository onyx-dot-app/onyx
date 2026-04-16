#!/usr/bin/env bash

set -euo pipefail

echo "Setting up firewall..."

# Reset default policies to ACCEPT before flushing rules.  On re-runs the
# previous invocation's DROP policies are still in effect; flushing rules while
# the default is DROP would block the DNS lookups below.  Register a trap so
# that if the script exits before the DROP policies are re-applied at the end,
# we fail closed instead of leaving the container with an unrestricted
# firewall.
trap 'iptables -P INPUT DROP; iptables -P OUTPUT DROP; iptables -P FORWARD DROP' EXIT
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -P FORWARD ACCEPT

# Only flush the filter table.  The nat and mangle tables are managed by Docker
# (DNS DNAT to 127.0.0.11, container networking, etc.) and must not be touched —
# flushing them breaks Docker's embedded DNS resolver.
iptables -F
iptables -X

# Create ipset for allowed destinations
ipset create allowed-domains hash:net || true
ipset flush allowed-domains

# Fetch GitHub IP ranges (IPv4 only -- ipset hash:net and iptables are IPv4)
GITHUB_IPS=$(curl -s https://api.github.com/meta | jq -r '.api[]' 2>/dev/null | grep -v ':' || echo "")
for ip in $GITHUB_IPS; do
    if ! ipset add allowed-domains "$ip" -exist 2>&1; then
        echo "warning: failed to add GitHub IP $ip to allowlist" >&2
    fi
done

# Resolve allowed domains
ALLOWED_DOMAINS=(
    "github.com"
    "registry.npmjs.org"
    "api.anthropic.com"
    "api-staging.anthropic.com"
    "files.anthropic.com"
    "sentry.io"
    "update.code.visualstudio.com"
    "pypi.org"
    "files.pythonhosted.org"
    "go.dev"
    "proxy.golang.org"
    "sum.golang.org"
    "storage.googleapis.com"
    "dl.google.com"
    "static.rust-lang.org"
    "index.crates.io"
    "static.crates.io"
    "archive.ubuntu.com"
    "security.ubuntu.com"
    "deb.nodesource.com"
)

for domain in "${ALLOWED_DOMAINS[@]}"; do
    IPS=$(getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | grep -v ':' | sort -u || echo "")
    for ip in $IPS; do
        if ! ipset add allowed-domains "$ip/32" -exist 2>&1; then
            echo "warning: failed to add $domain ($ip) to allowlist" >&2
        fi
    done
done

# Allow traffic to the Docker gateway so the container can reach host services
# (e.g. the Onyx stack at localhost:3000, localhost:8080, etc.)
DOCKER_GATEWAY=$(ip -4 route show default | awk '{print $3}')
if [ -n "$DOCKER_GATEWAY" ]; then
    if ! ipset add allowed-domains "$DOCKER_GATEWAY/32" -exist 2>&1; then
        echo "warning: failed to add Docker gateway $DOCKER_GATEWAY to allowlist" >&2
    fi
fi

# Allow traffic to all attached Docker network subnets so the container can
# reach sibling services (e.g. relational_db, cache) on shared compose networks.
for subnet in $(ip -4 -o addr show scope global | awk '{print $4}'); do
    if ! ipset add allowed-domains "$subnet" -exist 2>&1; then
        echo "warning: failed to add Docker subnet $subnet to allowlist" >&2
    fi
done

# Set default policies to DROP
iptables -P FORWARD DROP
iptables -P INPUT DROP
iptables -P OUTPUT DROP

# Allow established connections
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Allow loopback
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Allow DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# Allow outbound to allowed destinations
iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT

# Reject unauthorized outbound
iptables -A OUTPUT -j REJECT --reject-with icmp-host-unreachable

# Validate firewall configuration
echo "Validating firewall configuration..."

BLOCKED_SITES=("example.com" "google.com" "facebook.com")
for site in "${BLOCKED_SITES[@]}"; do
    if timeout 2 ping -c 1 "$site" &>/dev/null; then
        echo "Warning: $site is still reachable"
    fi
done

if ! timeout 5 curl -s https://api.github.com/meta > /dev/null; then
    echo "Warning: GitHub API is not accessible"
fi

echo "Firewall setup complete"
