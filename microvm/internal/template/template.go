// Package template reads the VM templates on a node.
//
// A template is a Firecracker snapshot in <store>/<version>/:
//
//	manifest.json  Manifest
//	rootfs.ext4    read-only root drive (drive_id "rootfs")
//	scratch.ext4   scratch drive at snapshot time (drive_id "scratch")
//	vmstate        snapshot state
//	mem            snapshot memory
//
// The snapshot must be taken inside a jailer chroot, so that the drive paths
// in vmstate are /rootfs.ext4 and /scratch.ext4 and the vsock UDS is /v.sock.
// Every VM chroot then has the same layout.
package template

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// File names in a template directory and in each VM chroot.
const (
	ManifestFile = "manifest.json"
	RootfsFile   = "rootfs.ext4"
	ScratchFile  = "scratch.ext4"
	VMStateFile  = "vmstate"
	MemFile      = "mem"
)

// Drive IDs and the vsock UDS path that the snapshot must use.
const (
	RootfsDriveID  = "rootfs"
	ScratchDriveID = "scratch"
	VsockUDS       = "/v.sock"
	GuestCID       = 3
)

var versionRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

// Manifest describes one template.
type Manifest struct {
	Version            string `json:"version"`
	VCPUs              uint32 `json:"vcpus"`
	MemMiB             uint32 `json:"mem_mib"`
	ScratchGiB         uint32 `json:"scratch_gib"`
	GuestKernel        string `json:"guest_kernel"`
	FirecrackerVersion string `json:"firecracker_version"`
}

// Template is a manifest and its directory.
type Template struct {
	Manifest
	Dir string
}

// Path returns the path of a file in the template directory.
func (t *Template) Path(name string) string { return filepath.Join(t.Dir, name) }

// Store is the template directory of a node.
type Store struct {
	Dir string
}

// ValidVersion reports whether v is a safe template version name.
func ValidVersion(v string) bool { return versionRE.MatchString(v) }

// Get loads and checks one template.
func (s *Store) Get(version string) (*Template, error) {
	if !ValidVersion(version) {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "template %q is not a valid version name", version)
	}
	dir := filepath.Join(s.Dir, version)
	raw, err := os.ReadFile(filepath.Join(dir, ManifestFile))
	if errors.Is(err, fs.ErrNotExist) {
		return nil, apierr.New(pb.ErrorReason_TEMPLATE_MISSING, "template %q is not on this node", version)
	}
	if err != nil {
		return nil, fmt.Errorf("read template %q manifest: %w", version, err)
	}
	var m Manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, fmt.Errorf("parse template %q manifest: %w", version, err)
	}
	if m.Version != version {
		return nil, fmt.Errorf("template %q manifest has version %q", version, m.Version)
	}
	if m.VCPUs == 0 || m.MemMiB == 0 || m.ScratchGiB == 0 {
		return nil, fmt.Errorf("template %q manifest has a zero vcpus, mem_mib or scratch_gib", version)
	}
	for _, f := range []string{RootfsFile, ScratchFile, VMStateFile, MemFile} {
		st, err := os.Stat(filepath.Join(dir, f))
		if err != nil {
			return nil, apierr.New(pb.ErrorReason_TEMPLATE_MISSING, "template %q has no %s: %v", version, f, err)
		}
		if !st.Mode().IsRegular() {
			return nil, apierr.New(pb.ErrorReason_TEMPLATE_MISSING, "template %q %s is not a regular file", version, f)
		}
	}
	return &Template{Manifest: m, Dir: dir}, nil
}

// List returns every valid template, sorted by version. It skips directories
// that are not complete templates.
func (s *Store) List() ([]*Template, error) {
	entries, err := os.ReadDir(s.Dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []*Template
	for _, e := range entries {
		if !e.IsDir() || !ValidVersion(e.Name()) {
			continue
		}
		t, getErr := s.Get(e.Name())
		if getErr != nil {
			continue
		}
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Version < out[j].Version })
	return out, nil
}

// WriteManifest writes m to dir atomically.
func WriteManifest(dir string, m Manifest) error {
	raw, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	tmp := filepath.Join(dir, ManifestFile+".tmp")
	if err := os.WriteFile(tmp, append(raw, '\n'), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(dir, ManifestFile))
}
