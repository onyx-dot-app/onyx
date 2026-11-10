// Package tplbuild builds the VM template of a node from a root drive.
//
// The input is the output of deployment/craft-fc/rootfs/build-rootfs.sh: a
// directory with rootfs.ext4 and manifest.json. The node agent does not run
// Docker; it only boots that drive and snapshots it.
package tplbuild

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// Rootfs input file names.
const (
	RootfsManifestFile = "manifest.json"
	RootfsImageFile    = "rootfs.ext4"
)

// DeferArg makes the guest init skip the scratch and managed drives at boot.
// A template must never have the scratch drive mounted.
const DeferArg = "craft.scratch=defer"

// RootfsManifest is the part of the build-rootfs.sh manifest that the
// template build reads.
type RootfsManifest struct {
	Schema      int    `json:"schema"`
	Kind        string `json:"kind"`
	SourceImage struct {
		Ref    string `json:"ref"`
		Pinned string `json:"pinned"`
		Digest string `json:"digest"`
	} `json:"source_image"`
	BuildInputs struct {
		EgressCA struct {
			Fingerprint string `json:"sha256_fingerprint"`
		} `json:"egress_ca"`
	} `json:"build_inputs"`
	Guest struct {
		BootArgs     string `json:"boot_args"`
		TemplateArgs string `json:"template_boot_args_extra"`
		Drives       []struct {
			DriveID    string `json:"drive_id"`
			IsReadOnly bool   `json:"is_read_only"`
		} `json:"drives"`
		Daemon struct {
			VsockPort uint32 `json:"vsock_port"`
		} `json:"daemon"`
	} `json:"guest"`
	Output struct {
		File      string `json:"file"`
		SHA256    string `json:"sha256"`
		SizeBytes int64  `json:"size_bytes"`
	} `json:"output"`
}

// Rootfs is one root drive build.
type Rootfs struct {
	// Path is the rootfs.ext4 file.
	Path     string
	Manifest RootfsManifest
	// ManifestSHA256 identifies the build (the drive is not reproducible
	// byte for byte).
	ManifestSHA256 string
}

var sha256RE = regexp.MustCompile(`^[0-9a-f]{64}$`)

// LoadRootfs reads a build-rootfs.sh output directory. It checks the
// manifest; Build checks the drive hash.
func LoadRootfs(dir string) (*Rootfs, error) {
	raw, err := os.ReadFile(filepath.Join(dir, RootfsManifestFile))
	if err != nil {
		return nil, apierr.New(pb.ErrorReason_TEMPLATE_MISSING, "rootfs manifest: %v", err)
	}
	var m RootfsManifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "rootfs manifest %s: %v", dir, err)
	}
	if m.Kind != "craft-fc-rootfs" || m.Schema != 1 {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "rootfs manifest %s: kind %q schema %d, want craft-fc-rootfs 1", dir, m.Kind, m.Schema)
	}
	if err := checkDrives(m); err != nil {
		return nil, apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE, "rootfs %s: %v", dir, err)
	}
	if !sha256RE.MatchString(m.Output.SHA256) || m.Output.File != RootfsImageFile {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "rootfs manifest %s: output must be %s with a SHA256", dir, RootfsImageFile)
	}
	if strings.TrimSpace(m.Guest.BootArgs) == "" {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "rootfs manifest %s has no boot_args", dir)
	}
	sum := sha256.Sum256(raw)
	return &Rootfs{Path: filepath.Join(dir, RootfsImageFile), Manifest: m, ManifestSHA256: hex.EncodeToString(sum[:])}, nil
}

// checkDrives checks that the root drive expects the template's first drive
// slots (rootfs, scratch, managed) in that order.
func checkDrives(m RootfsManifest) error {
	want := template.Drives[:3]
	if len(m.Guest.Drives) != len(want) {
		return fmt.Errorf("the root drive lists %d drives, the agent has %d (rootfs, scratch, managed)", len(m.Guest.Drives), len(want))
	}
	for i, d := range m.Guest.Drives {
		if d.DriveID != want[i].ID || d.IsReadOnly != want[i].ReadOnly {
			return fmt.Errorf("drive %d is %s (read-only %v), the agent has %s (read-only %v)", i, d.DriveID, d.IsReadOnly, want[i].ID, want[i].ReadOnly)
		}
	}
	return nil
}

// BootArgs returns the template boot arguments: the guest boot_args, the
// template extra and always DeferArg.
func (r *Rootfs) BootArgs() string {
	args := strings.Fields(r.Manifest.Guest.BootArgs + " " + r.Manifest.Guest.TemplateArgs)
	has := false
	for _, a := range args {
		if a == DeferArg {
			has = true
		}
	}
	if !has {
		args = append(args, DeferArg)
	}
	return strings.Join(args, " ")
}

// CAFingerprint returns the rootfs egress CA fingerprint, normalized.
func (r *Rootfs) CAFingerprint() string {
	return NormalizeFingerprint(r.Manifest.BuildInputs.EgressCA.Fingerprint)
}

// NormalizeFingerprint makes "AB:CD:..." (openssl) and "abcd..." equal.
func NormalizeFingerprint(fp string) string {
	return strings.ToLower(strings.ReplaceAll(strings.TrimSpace(fp), ":", ""))
}

// CAFileFingerprint returns the SHA256 fingerprint of the one PEM
// certificate in path (the egress CA of the deployment), normalized.
func CAFileFingerprint(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	block, rest := pem.Decode(raw)
	if block == nil || block.Type != "CERTIFICATE" {
		return "", fmt.Errorf("%s has no PEM certificate", path)
	}
	if b2, _ := pem.Decode(rest); b2 != nil {
		return "", fmt.Errorf("%s has more than one PEM block", path)
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return "", fmt.Errorf("%s: %w", path, err)
	}
	if !cert.IsCA {
		return "", errors.New(path + " is not a CA certificate")
	}
	sum := sha256.Sum256(block.Bytes)
	return hex.EncodeToString(sum[:]), nil
}

var tagRE = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

// Name returns the template version for a key: "<image tag>-<key hash[:12]>".
func Name(imageRef, keySHA string) string {
	tag := "img"
	ref := imageRef
	if i := strings.LastIndex(ref, "@"); i >= 0 {
		ref = ref[:i]
	}
	if i := strings.LastIndex(ref, ":"); i >= 0 && !strings.Contains(ref[i:], "/") {
		tag = ref[i+1:]
	}
	tag = strings.Trim(tagRE.ReplaceAllString(tag, "-"), "-._")
	if tag == "" {
		tag = "img"
	}
	if len(tag) > 40 {
		tag = tag[:40]
	}
	return tag + "-" + keySHA[:12]
}
