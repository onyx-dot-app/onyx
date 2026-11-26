package main

import (
	"crypto/tls"
	"flag"
	"fmt"
	"net"
	"os"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/vsock"
)

// listenConfig selects the daemon's listener.
type listenConfig struct {
	// Spec is "" (vsock on Port), unix:<path> or tcp:<host:port>.
	Spec    string
	Port    uint
	TLSCert string
	TLSKey  string
	KeyFile string
}

// listen opens the listener and returns the gRPC transport options for it.
// TCP needs TLS and a key file: on a network the first caller would
// otherwise set the key, and the key would travel in plaintext.
func listen(c listenConfig) (net.Listener, []grpc.ServerOption, error) {
	tcpAddr, isTCP := strings.CutPrefix(c.Spec, "tcp:")
	unixPath, isUnix := strings.CutPrefix(c.Spec, "unix:")
	hasTLS := c.TLSCert != "" || c.TLSKey != ""
	switch {
	case isTCP:
		if tcpAddr == "" {
			return nil, nil, fmt.Errorf("--listen tcp: needs an address, for example tcp:0.0.0.0:8052")
		}
		if c.TLSCert == "" || c.TLSKey == "" {
			return nil, nil, fmt.Errorf("--listen tcp: needs --tls-cert and --tls-key")
		}
		if c.KeyFile == "" {
			return nil, nil, fmt.Errorf("--listen tcp: needs --key-file")
		}
		cert, err := tls.LoadX509KeyPair(c.TLSCert, c.TLSKey)
		if err != nil {
			return nil, nil, fmt.Errorf("load the TLS certificate: %w", err)
		}
		creds := credentials.NewTLS(&tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS13})
		ln, err := net.Listen("tcp", tcpAddr)
		if err != nil {
			return nil, nil, err
		}
		return ln, []grpc.ServerOption{grpc.Creds(creds)}, nil
	case hasTLS:
		return nil, nil, fmt.Errorf("--tls-cert and --tls-key need --listen tcp:<addr>")
	case isUnix && unixPath != "":
		_ = os.Remove(unixPath)
		ln, err := net.Listen("unix", unixPath)
		if err == nil {
			if err = os.Chmod(unixPath, 0o600); err != nil {
				_ = ln.Close()
			}
		}
		return ln, nil, err
	case c.Spec != "":
		return nil, nil, fmt.Errorf("--listen must be unix:<path> or tcp:<addr>, got %q", c.Spec)
	default:
		ln, err := vsock.Listen(uint32(c.Port))
		return ln, nil, err
	}
}

// readKeyFile returns the key in path, without surrounding white space. An
// empty file is an error: the first SetKey caller would get the daemon.
func readKeyFile(path string) (string, error) {
	if path == "" {
		return "", nil
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	key := strings.TrimSpace(string(raw))
	if key == "" {
		return "", fmt.Errorf("%s is empty", path)
	}
	return key, nil
}

// containerDefaults turn off the VM-only parts: drives, the egress relay,
// the balloon, the CA install (firewall-init installs the proxy CA), the
// cgroup mount and the root-only user switch. Init skips the clock and
// entropy.
var containerDefaults = map[string]string{
	"attach-cmd":           "",
	"relay-pidfile":        "",
	"grow-fs":              "",
	"managed-mounts":       "",
	"page-reporting-order": "-1",
	"reclaim-idle":         "0",
	"ca-bundle":            "",
	"cgroup-root":          "",
	"state-file":           "",
	"command-user":         "",
	"file-owner":           "",
}

// applyContainerDefaults sets each containerDefaults flag that the command
// line did not set.
func applyContainerDefaults(fs *flag.FlagSet) error {
	set := map[string]bool{}
	fs.Visit(func(f *flag.Flag) { set[f.Name] = true })
	for name, value := range containerDefaults {
		if set[name] {
			continue
		}
		if err := fs.Set(name, value); err != nil {
			return fmt.Errorf("--container default --%s=%q: %w", name, value, err)
		}
	}
	return nil
}
