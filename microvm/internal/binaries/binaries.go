// Package binaries installs the pinned Firecracker and jailer binaries into
// the data dir, so that the host mount namespace can run them.
package binaries

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Firecracker v1.17.0 x86_64 release binaries, from the release SHA256SUMS
// (the same release that deployment/craft-fc/Dockerfile.artifacts pins).
const (
	FirecrackerVersion = "v1.17.0"
	FirecrackerSHA256  = "99ad0f5cd0514a88aad0e9ae8cfdb3cc3b4ab9d190e1194602406c786b5de7a5"
	JailerSHA256       = "65ef226e96f0ceda55ba643f445801ef2cc0ea667ef67cad8ac4f406c9c8434f"
)

// Installed are the host paths of the installed binaries.
type Installed struct {
	Firecracker string
	Jailer      string
	// Version is the output of "firecracker --version", for example "v1.17.0".
	Version string
}

// Install copies <srcDir>/firecracker and <srcDir>/jailer to
// <binDir>/<version>/ after it checks their SHA256. An existing correct copy
// is kept, so running VMs never see a binary change under them.
func Install(srcDir, binDir, version, fcSHA, jailerSHA string) (*Installed, error) {
	dst := filepath.Join(binDir, version)
	if err := os.MkdirAll(dst, 0o755); err != nil {
		return nil, err
	}
	out := &Installed{Firecracker: filepath.Join(dst, "firecracker"), Jailer: filepath.Join(dst, "jailer")}
	if err := installOne(filepath.Join(srcDir, "firecracker"), out.Firecracker, fcSHA); err != nil {
		return nil, err
	}
	if err := installOne(filepath.Join(srcDir, "jailer"), out.Jailer, jailerSHA); err != nil {
		return nil, err
	}
	raw, err := exec.Command(out.Firecracker, "--version").Output()
	if err != nil {
		return nil, fmt.Errorf("firecracker --version: %w", err)
	}
	out.Version = ParseVersion(string(raw))
	if out.Version != version {
		return nil, fmt.Errorf("firecracker reports version %q, want %q", out.Version, version)
	}
	return out, nil
}

// ParseVersion returns "v1.17.0" from "Firecracker v1.17.0\n...".
func ParseVersion(out string) string {
	first, _, _ := strings.Cut(out, "\n")
	f := strings.Fields(first)
	if len(f) == 2 && f[0] == "Firecracker" {
		return f[1]
	}
	return ""
}

func installOne(src, dst, want string) error {
	if got, err := fileSHA256(dst); err == nil && got == want {
		return nil
	}
	got, err := fileSHA256(src)
	if err != nil {
		return err
	}
	if got != want {
		return fmt.Errorf("%s has SHA256 %s, want %s", src, got, want)
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
	tmp, err := os.CreateTemp(filepath.Dir(dst), "."+filepath.Base(dst)+".*")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := io.Copy(tmp, in); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Chmod(0o755); err != nil {
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
	if got, err := fileSHA256(tmp.Name()); err != nil || got != want {
		return fmt.Errorf("copy of %s does not match its SHA256", src)
	}
	return os.Rename(tmp.Name(), dst)
}

func fileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() { _ = f.Close() }()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// Kernel is the installed guest kernel.
type Kernel struct {
	Path    string
	SHA256  string
	Release string
}

// InstallKernel copies the guest kernel src to <dir>/vmlinux-<sha256[:16]>
// on the data dir file system (VM chroots get reflink copies of it) and
// reads its release from the Linux banner. An existing copy is kept.
func InstallKernel(src, dir string) (*Kernel, error) {
	sum, err := fileSHA256(src)
	if err != nil {
		return nil, fmt.Errorf("guest kernel: %w", err)
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	dst := filepath.Join(dir, "vmlinux-"+sum[:16])
	if err := installOne(src, dst, sum); err != nil {
		return nil, err
	}
	rel, err := KernelRelease(dst)
	if err != nil {
		return nil, err
	}
	return &Kernel{Path: dst, SHA256: sum, Release: rel}, nil
}

// KernelRelease returns the release in the "Linux version <release> " banner
// of an uncompressed kernel image.
func KernelRelease(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	const banner = "Linux version "
	i := bytes.Index(raw, []byte(banner))
	if i < 0 {
		return "", fmt.Errorf("%s has no Linux version banner", path)
	}
	rest := raw[i+len(banner):]
	if j := bytes.IndexAny(rest, " \x00\n"); j > 0 {
		return string(rest[:j]), nil
	}
	return "", fmt.Errorf("%s has a bad Linux version banner", path)
}
