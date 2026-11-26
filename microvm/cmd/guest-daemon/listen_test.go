package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"flag"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

var testKey = strings.Repeat("k", 32)

func writeFile(t *testing.T, dir, name string, data []byte) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, data, 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestListenRefusesTCPWithoutTLSOrKey(t *testing.T) {
	dir := t.TempDir()
	cert, key := writeFile(t, dir, "c.pem", nil), writeFile(t, dir, "k.pem", nil)
	kf := writeFile(t, dir, "key", []byte(testKey))
	for _, c := range []listenConfig{
		{Spec: "tcp:127.0.0.1:0", KeyFile: kf},
		{Spec: "tcp:127.0.0.1:0", TLSCert: cert, KeyFile: kf},
		{Spec: "tcp:127.0.0.1:0", TLSKey: key, KeyFile: kf},
		{Spec: "tcp:127.0.0.1:0", TLSCert: cert, TLSKey: key},
		{Spec: "tcp:", TLSCert: cert, TLSKey: key, KeyFile: kf},
		{Spec: "unix:" + filepath.Join(dir, "s"), TLSCert: cert, TLSKey: key},
		{TLSCert: cert, TLSKey: key},
		{Spec: "http://127.0.0.1:1"},
	} {
		if ln, _, err := listen(c); err == nil {
			_ = ln.Close()
			t.Errorf("%+v: no error", c)
		}
	}
}

// The TCP listener serves gRPC over TLS 1.3 only; a plaintext client gets
// nothing, and the key from the key file guards every call but Health.
func TestListenTCPServesTLS(t *testing.T) {
	ca, err := testcerts.NewCA("sandbox")
	if err != nil {
		t.Fatal(err)
	}
	certPEM, keyPEM, err := ca.Leaf("daemon", true)
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	kf := writeFile(t, dir, "key", []byte(testKey+"\n"))
	ln, transport, err := listen(listenConfig{
		Spec: "tcp:127.0.0.1:0", TLSCert: writeFile(t, dir, "c.pem", certPEM),
		TLSKey: writeFile(t, dir, "k.pem", keyPEM), KeyFile: kf,
	})
	if err != nil {
		t.Fatal(err)
	}
	key, err := readKeyFile(kf)
	if err != nil || key != testKey {
		t.Fatalf("key file: %q %v", key, err)
	}
	if _, err := readKeyFile(writeFile(t, dir, "empty", []byte(" \n"))); err == nil {
		t.Fatal("empty key file: no error")
	}
	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	srv, err := guestd.NewServer(guestd.Config{Version: "test", Key: key}, guestd.System{}, m)
	if err != nil {
		t.Fatal(err)
	}
	gs := srv.NewGRPCServer(transport...)
	go func() { _ = gs.Serve(ln) }()
	t.Cleanup(gs.Stop)
	addr := ln.Addr().String()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	plain, err := grpc.NewClient("passthrough:///"+addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = plain.Close() }()
	pctx, pcancel := context.WithTimeout(ctx, 2*time.Second)
	defer pcancel()
	if _, err := pb.NewSandboxdClient(plain).Health(pctx, &pb.HealthRequest{}); err == nil {
		t.Fatal("plaintext Health succeeded")
	}

	tls12 := &tls.Config{RootCAs: certPool(ca.PEM), MaxVersion: tls.VersionTLS12, MinVersion: tls.VersionTLS12}
	old, err := grpc.NewClient("passthrough:///"+addr, grpc.WithTransportCredentials(credentials.NewTLS(tls12)))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = old.Close() }()
	if _, err := pb.NewSandboxdClient(old).Health(pctx, &pb.HealthRequest{}); err == nil {
		t.Fatal("TLS 1.2 Health succeeded")
	}

	conn, err := grpc.NewClient("passthrough:///"+addr, grpc.WithTransportCredentials(
		credentials.NewTLS(&tls.Config{RootCAs: certPool(ca.PEM), ServerName: "localhost", MinVersion: tls.VersionTLS13})))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	c := pb.NewSandboxdClient(conn)
	h, err := c.Health(ctx, &pb.HealthRequest{})
	if err != nil || !h.GetKeySet() || h.GetInitialized() {
		t.Fatalf("health over TLS: %v %v", h, err)
	}
	if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: strings.Repeat("x", 32)}); err == nil {
		t.Fatal("SetKey replaced the key file key")
	}
	if _, err := c.Init(ctx, &pb.InitRequest{}); err == nil {
		t.Fatal("Init without the key succeeded")
	}
}

func certPool(pem []byte) *x509.CertPool {
	p := x509.NewCertPool()
	p.AppendCertsFromPEM(pem)
	return p
}

func TestApplyContainerDefaults(t *testing.T) {
	fs := flag.NewFlagSet("t", flag.ContinueOnError)
	vals := map[string]*string{}
	for name := range containerDefaults {
		vals[name] = fs.String(name, "vm-default", "")
	}
	if err := fs.Parse([]string{"--cgroup-root=/sys/fs/cgroup/x"}); err != nil {
		t.Fatal(err)
	}
	if err := applyContainerDefaults(fs); err != nil {
		t.Fatal(err)
	}
	for name, want := range containerDefaults {
		if name == "cgroup-root" {
			want = "/sys/fs/cgroup/x"
		}
		if got := *vals[name]; got != want {
			t.Errorf("--%s = %q, want %q", name, got, want)
		}
	}
}
