//go:build unix

package sysops

import (
	"bytes"
	"context"
	"encoding/pem"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/egressca"
)

// CAPaths are the guest trust stores that InstallEgressCA writes. The
// defaults are the paths of build-rootfs.sh and the Debian image.
type CAPaths struct {
	// Anchor is the CA file that update-ca-certificates reads, so a later
	// update (for example from apt) keeps the CA in the bundle.
	Anchor string
	// Bundle is the system bundle (/etc/ssl/sandbox/ca-bundle.crt links to it).
	Bundle string
	// NSSDB is the sandbox user's Chromium NSS database. Empty: skipped.
	NSSDB string
	// Certutil is the NSS tool. Empty: /usr/bin/certutil.
	Certutil string
	// Nickname is the NSS name of the CA.
	Nickname string
	Log      *slog.Logger
}

// DefaultCAPaths are the stores of the Craft root drive.
var DefaultCAPaths = CAPaths{
	Anchor:   "/usr/local/share/ca-certificates/craft-egress-ca.crt",
	Bundle:   "/etc/ssl/certs/ca-certificates.crt",
	NSSDB:    "/home/sandbox/.pki/nssdb",
	Certutil: "/usr/bin/certutil",
	Nickname: "craft-egress-ca",
}

// InstallEgressCA puts the CA into the trust stores. It replaces the CA of
// an earlier call: the old anchor's certificate is removed from the bundle
// and from the NSS database. A failed anchor or bundle write is an error; a
// failed NSS update is only logged (Chromium then does not trust the proxy,
// other programs do).
//
// The bundle is written before the anchor, so the anchor names the CA to
// remove until the bundle no longer has it. A failed anchor write restores
// the old bundle. If that also fails, no anchor names the CA in the bundle,
// so all later calls in this process fail.
func InstallEgressCA(p CAPaths, caPEM []byte) error {
	caMu.Lock()
	defer caMu.Unlock()
	if caBroken != nil {
		return caBroken
	}
	ca, err := egressca.Parse(caPEM)
	if err != nil {
		return err
	}
	drop := [][]byte{ca.Cert.Raw}
	if raw, err := os.ReadFile(p.Anchor); err == nil {
		if old, err := egressca.Parse(raw); err == nil {
			drop = append(drop, old.Cert.Raw)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read %s: %w", p.Anchor, err)
	}
	bundle, err := os.ReadFile(p.Bundle)
	hadBundle := err == nil
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read %s: %w", p.Bundle, err)
	}
	if err := writeFile(p.Bundle, ReplaceInBundle(bundle, drop, ca.PEM), 0o644); err != nil {
		return fmt.Errorf("write %s: %w", p.Bundle, err)
	}
	err = os.MkdirAll(filepath.Dir(p.Anchor), 0o755)
	if err == nil {
		err = writeFile(p.Anchor, ca.PEM, 0o644)
	}
	if err != nil {
		err = fmt.Errorf("write %s: %w", p.Anchor, err)
		var rerr error
		if hadBundle {
			rerr = writeFile(p.Bundle, bundle, 0o644)
		} else if rerr = os.Remove(p.Bundle); errors.Is(rerr, os.ErrNotExist) {
			rerr = nil
		}
		if rerr != nil {
			caBroken = fmt.Errorf("egress CA trust store is inconsistent: %w (restore %s: %v)", err, p.Bundle, rerr)
			return caBroken
		}
		return err
	}
	if p.NSSDB != "" {
		if err := installNSS(p, p.Anchor); err != nil {
			log := p.Log
			if log == nil {
				log = slog.Default()
			}
			log.Warn("egress CA not added to the NSS database", "db", p.NSSDB, "err", err)
		}
	}
	return nil
}

var (
	caMu sync.Mutex
	// caBroken is set when a failed install could not be undone.
	caBroken error
)

// ReplaceInBundle returns bundle without the certificates in drop (DER), with
// caPEM at the end. Text outside PEM blocks is dropped.
func ReplaceInBundle(bundle []byte, drop [][]byte, caPEM []byte) []byte {
	var out bytes.Buffer
	rest := bundle
	for {
		var b *pem.Block
		b, rest = pem.Decode(rest)
		if b == nil {
			break
		}
		if b.Type == "CERTIFICATE" && containsDER(drop, b.Bytes) {
			continue
		}
		_ = pem.Encode(&out, b)
	}
	out.Write(caPEM)
	return out.Bytes()
}

func containsDER(list [][]byte, der []byte) bool {
	for _, d := range list {
		if bytes.Equal(d, der) {
			return true
		}
	}
	return false
}

// writeFile is writeFileAtomic; tests replace it to fail a write.
var writeFile = writeFileAtomic

// writeFileAtomic writes a new file next to path and renames it over path.
// A link at path is replaced, not followed.
func writeFileAtomic(path string, data []byte, mode os.FileMode) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".tmp-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer func() { _ = os.Remove(name) }()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Chmod(mode); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}

// installNSS replaces the CA in the NSS database. certutil runs as the
// owner of the database, never as root: certutil is under the writable /usr
// overlay, and files it makes must stay readable by the browser user.
func installNSS(p CAPaths, certFile string) error {
	st, err := os.Stat(p.NSSDB)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	sys, ok := st.Sys().(*syscall.Stat_t)
	if !ok || !st.IsDir() {
		return fmt.Errorf("%s is not a directory", p.NSSDB)
	}
	if sys.Uid == 0 {
		return fmt.Errorf("%s is owned by root; certutil does not run as root", p.NSSDB)
	}
	tool := p.Certutil
	if tool == "" {
		tool = "/usr/bin/certutil"
	}
	if _, err := os.Stat(tool); err != nil {
		return fmt.Errorf("no certutil: %w", err)
	}
	nick := p.Nickname
	if nick == "" {
		nick = "craft-egress-ca"
	}
	db := "sql:" + p.NSSDB
	run := func(args ...string) error {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, tool, args...)
		cmd.Env = []string{"PATH=/usr/bin:/bin", "HOME=" + filepath.Dir(filepath.Dir(p.NSSDB))}
		// A daemon that is not root (tests) cannot drop supplementary groups.
		cmd.SysProcAttr = &syscall.SysProcAttr{Credential: &syscall.Credential{
			Uid: sys.Uid, Gid: sys.Gid, Groups: []uint32{}, NoSetGroups: os.Geteuid() != 0,
		}}
		cmd.WaitDelay = 5 * time.Second
		out, err := cmd.CombinedOutput()
		if err != nil {
			return fmt.Errorf("certutil %s: %w: %s", strings.Join(args, " "), err, strings.TrimSpace(tail(out, 500)))
		}
		return nil
	}
	// -D removes one entry per call; an older database can hold the name twice.
	for range 4 {
		if run("-D", "-d", db, "-n", nick) != nil {
			break
		}
	}
	return run("-A", "-d", db, "-n", nick, "-t", "C,,", "-i", certFile)
}
