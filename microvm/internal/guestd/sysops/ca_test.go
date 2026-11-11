//go:build unix

package sysops

import (
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
)

func newTestCA(t *testing.T, name string) *testcerts.CA {
	t.Helper()
	ca, err := testcerts.NewCA(name)
	if err != nil {
		t.Fatal(err)
	}
	return ca
}

// certs returns the CommonNames of the certificates in a PEM bundle.
func certs(t *testing.T, path string) []string {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for {
		var b *pem.Block
		b, raw = pem.Decode(raw)
		if b == nil {
			return out
		}
		c, err := x509.ParseCertificate(b.Bytes)
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, c.Subject.CommonName)
	}
}

func TestInstallEgressCA(t *testing.T) {
	dir := t.TempDir()
	pub1, pub2 := newTestCA(t, "public one"), newTestCA(t, "public two")
	ca1, ca2 := newTestCA(t, "egress one"), newTestCA(t, "egress two")
	p := CAPaths{
		Anchor: filepath.Join(dir, "usr/local/share/ca-certificates/craft-egress-ca.crt"),
		Bundle: filepath.Join(dir, "ca-certificates.crt"),
	}
	if err := os.WriteFile(p.Bundle, append(append([]byte{}, pub1.PEM...), pub2.PEM...), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := InstallEgressCA(p, ca1.PEM); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(certs(t, p.Bundle), ","); got != "public one,public two,egress one" {
		t.Fatalf("bundle %s", got)
	}
	if got := strings.Join(certs(t, p.Anchor), ","); got != "egress one" {
		t.Fatalf("anchor %s", got)
	}
	// A new CA replaces the old one (a CA rotation, or a saved disk whose
	// overlay holds the old bundle).
	if err := InstallEgressCA(p, ca2.PEM); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(certs(t, p.Bundle), ","); got != "public one,public two,egress two" {
		t.Fatalf("bundle after rotation %s", got)
	}
	// Idempotent.
	if err := InstallEgressCA(p, ca2.PEM); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(certs(t, p.Bundle), ","); got != "public one,public two,egress two" {
		t.Fatalf("bundle after a repeat %s", got)
	}
	if st, _ := os.Stat(p.Bundle); st.Mode().Perm() != 0o644 {
		t.Fatalf("bundle mode %v", st.Mode())
	}
	// A link at the bundle path is replaced, not followed.
	target := filepath.Join(dir, "elsewhere.crt")
	if err := os.WriteFile(target, pub1.PEM, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(p.Bundle); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, p.Bundle); err != nil {
		t.Fatal(err)
	}
	if err := InstallEgressCA(p, ca1.PEM); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(certs(t, target), ","); got != "public one" {
		t.Fatalf("link target changed: %s", got)
	}
	if got := strings.Join(certs(t, p.Bundle), ","); got != "public one,egress one" {
		t.Fatalf("bundle %s", got)
	}
	if err := InstallEgressCA(p, []byte("not a CA")); err == nil {
		t.Fatal("bad PEM accepted")
	}
	if ents, _ := filepath.Glob(filepath.Join(dir, ".*.tmp-*")); len(ents) != 0 {
		t.Fatalf("temp files left: %v", ents)
	}
}

func TestInstallEgressCANSS(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("certutil never runs as root; the test makes the database as the current user")
	}
	dir := t.TempDir()
	log := filepath.Join(dir, "certutil.log")
	tool := filepath.Join(dir, "certutil")
	script := "#!/bin/sh\necho \"$(id -u) $*\" >> " + log + "\ncase \"$1\" in -D) exit 255;; esac\n"
	if err := os.WriteFile(tool, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	db := filepath.Join(dir, "home/sandbox/.pki/nssdb")
	if err := os.MkdirAll(db, 0o700); err != nil {
		t.Fatal(err)
	}
	p := CAPaths{
		Anchor: filepath.Join(dir, "anchor.crt"), Bundle: filepath.Join(dir, "bundle.crt"),
		NSSDB: db, Certutil: tool, Nickname: "craft-egress-ca",
	}
	if err := InstallEgressCA(p, newTestCA(t, "egress").PEM); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(log)
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	uid := strings.TrimSpace(strings.Fields(lines[0])[0])
	want := []string{
		uid + " -D -d sql:" + db + " -n craft-egress-ca",
		uid + " -A -d sql:" + db + " -n craft-egress-ca -t C,, -i " + p.Anchor,
	}
	if strings.Join(lines, "\n") != strings.Join(want, "\n") {
		t.Fatalf("certutil calls:\n%s\nwant:\n%s", raw, strings.Join(want, "\n"))
	}
	// A failing certutil does not fail the install (the system store is set).
	if err := os.WriteFile(tool, []byte("#!/bin/sh\nexit 1\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := InstallEgressCA(p, newTestCA(t, "egress two").PEM); err != nil {
		t.Fatal(err)
	}
	// No database: skipped.
	p.NSSDB = filepath.Join(dir, "none")
	if err := InstallEgressCA(p, newTestCA(t, "egress three").PEM); err != nil {
		t.Fatal(err)
	}
}
