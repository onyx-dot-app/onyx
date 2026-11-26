// Package containertest checks a guest daemon that runs in the craft-runtime
// container image (deployment/craft-runtime/check-container.sh starts it).
// Env: SANDBOXD_ADDR (host:port), SANDBOXD_CA (the daemon's certificate,
// PEM file), SANDBOXD_KEY (key file), SANDBOXD_LOCKDOWN=1 when
// firewall-init locked egress down.
package containertest
