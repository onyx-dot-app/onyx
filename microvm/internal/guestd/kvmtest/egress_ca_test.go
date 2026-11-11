//go:build kvm && linux

package kvmtest

import (
	"context"
	"net"
	"os"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// Guest clients reach the host vsock port 3128 through the in-guest relay
// (HTTPS_PROXY=127.0.0.1:3128 from guest.env).
const (
	guestCurl = `curl -sS --max-time 30 https://example.com/ 2>&1; echo "rc=$?"`
	guestPy   = `for p in /opt/onyx/python/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do [ -x $p ] && exec $p -c 'import urllib.request; print(urllib.request.urlopen("https://pypi.org/", timeout=30).read().decode().strip())' 2>&1; done; echo no python`
)

// testEgressCA runs a TLS-intercepting proxy on the VM's host vsock port
// 3128 and checks that guest clients trust the CA from SetKey, and only it.
func testEgressCA(ctx context.Context, t *testing.T, v *vm, c pb.SandboxdClient, key string) {
	t.Helper()
	ca1, err := testcerts.NewCA("egress-one")
	if err != nil {
		t.Fatal(err)
	}
	ca2, err := testcerts.NewCA("egress-two")
	if err != nil {
		t.Fatal(err)
	}
	uds := v.vsock() + "_3128"
	_ = os.Remove(uds)
	ln, err := net.Listen("unix", uds)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close(); _ = os.Remove(uds) }()
	mitm := testcerts.NewMITM(ca1)
	go mitm.Serve(ln)

	install := func(ca *testcerts.CA) {
		t.Helper()
		if _, err := c.SetKey(ctx, &pb.SetKeyRequest{Key: key, EgressCaPem: ca.PEM}); err != nil {
			t.Fatalf("SetKey with CA: %v", err)
		}
		r, err := c.Init(keyed(ctx, key), initRequest("init-main"))
		if err != nil || !r.GetEgressCaInstalled() {
			t.Fatalf("Init: %v %v", r, err)
		}
	}
	expect := func(what, script, want string, ok bool) {
		t.Helper()
		out := rootSh(ctx, t, c, key, script)
		t.Logf("%s: %s", what, strings.TrimSpace(out))
		if strings.Contains(out, want) != ok {
			t.Errorf("%s: want %q present=%v, got %q", what, want, ok, out)
		}
	}

	// The root drive has no egress CA: TLS through the proxy fails.
	expect("no CA yet", guestCurl, "mitm-ok", false)

	install(ca1)
	expect("curl, CA 1", guestCurl, "mitm-ok egress-one example.com", true)
	expect("python, CA 1", guestPy, "mitm-ok egress-one pypi.org", true)
	expect("NSS database", `runuser -u sandbox -- certutil -L -d sql:/home/sandbox/.pki/nssdb 2>&1`, "craft-egress-ca", true)
	expect("NSS owner", `stat -c 'owner=%U' /home/sandbox/.pki/nssdb/cert9.db`, "owner=sandbox", true)
	// apt runs update-ca-certificates; the anchor keeps the CA in the bundle.
	expect("after update-ca-certificates", `update-ca-certificates >/dev/null 2>&1; `+guestCurl, "mitm-ok egress-one", true)

	// CA rotation: the proxy signs with CA 2; the guest refuses it until the
	// next SetKey + Init.
	mitm.SetCA(ca2)
	expect("proxy CA 2, guest CA 1", guestCurl, "mitm-ok", false)
	install(ca2)
	expect("curl, CA 2", guestCurl, "mitm-ok egress-two example.com", true)
	expect("bundle has one egress CA", `grep -c BEGIN /usr/local/share/ca-certificates/craft-egress-ca.crt; runuser -u sandbox -- certutil -L -d sql:/home/sandbox/.pki/nssdb | grep -c craft-egress-ca`, "1\n1\n", true)
	mitm.SetCA(ca1)
	expect("old CA refused", guestCurl, "mitm-ok", false)
	// curl and python with CA 1, curl after update-ca-certificates, curl with CA 2.
	if n := mitm.Requests.Load(); n != 4 {
		t.Errorf("proxy answered %d HTTPS requests, want 4", n)
	}
}
