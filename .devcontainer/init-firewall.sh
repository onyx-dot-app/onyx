#!/usr/bin/env bash

set -euo pipefail

echo "Setting up firewall..."

# Preserve docker dns resolution
DOCKER_DNS_RULES=$(iptables-save | grep -E "^-A.*-d 127.0.0.11/32" || true)

# Flush all rules
iptables -t nat -F
iptables -t nat -X
iptables -t mangle -F
iptables -t mangle -X
iptables -F
iptables -X

# Restore docker dns rules
if [ -n "$DOCKER_DNS_RULES" ]; then
    echo "$DOCKER_DNS_RULES" | iptables-restore -n
fi

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
    "registry.npmjs.org"
    "api.anthropic.com"
    "api-staging.anthropic.com"
    "files.anthropic.com"
    "sentry.io"
    "update.code.visualstudio.com"
    "pypi.org"
    "files.pythonhosted.org"
    "go.dev"
    "storage.googleapis.com"
    "static.rust-lang.org"
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
