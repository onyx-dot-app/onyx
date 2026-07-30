package install

import (
	"crypto/rand"
	"encoding/hex"
	"os"

	"github.com/onyx-dot-app/onyx/cli/internal/version"
)

// Craft sandbox constants (names pinned to match the compose overlay's
// external declarations and the backend's configs).
const (
	defaultSandboxNetwork = "onyx_craft_sandbox"
	sandboxProxyCAVolume  = "sandbox_proxy_ca"
)

// sandboxNetworkName honors the same env override install.sh does.
func sandboxNetworkName() string {
	if n := os.Getenv("SANDBOX_DOCKER_NETWORK"); n != "" {
		return n
	}
	return defaultSandboxNetwork
}

// sandboxBackendForTag picks the Craft sandbox backend for an image tag: the
// docker backend exists only in v4.0.6+, so older pinned tags get
// "kubernetes" while rolling/non-semver tags (which track newest) get
// "docker". Mirrors install.sh's sandbox_backend_for_tag.
func sandboxBackendForTag(tag string) string {
	v, ok := version.Parse(tag)
	if !ok {
		return "docker"
	}
	if v.LessThan(version.Semver{Major: 4, Minor: 0, Patch: 6}) {
		return "kubernetes"
	}
	return "docker"
}

// randomHex returns n random bytes hex-encoded (install.sh: openssl rand -hex n).
func randomHex(n int) string {
	buf := make([]byte, n)
	if _, err := rand.Read(buf); err != nil {
		// crypto/rand failure means the platform's entropy source is broken;
		// panicking beats silently generating weak secrets.
		panic(err)
	}
	return hex.EncodeToString(buf)
}

// craftSecurityWarning is printed when Craft is enabled with the docker
// sandbox backend (ported verbatim from install.sh).
const craftSecurityWarning = `⚠  Craft + docker backend: api_server and background bind-mount
⚠  /var/run/docker.sock (RW = root on host on compromise);
⚠  sandbox-proxy bind-mounts it RO (still exposes container env,
⚠  labels, and the events stream). Only enable on hosts you fully
⚠  control. On EC2, require IMDSv2 (HttpTokens=required) so
⚠  sandboxes cannot pull IAM credentials from instance metadata.`
