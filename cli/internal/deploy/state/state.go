// Package state persists what the CLI last did to a deployment: the
// install-state.json manifest (installed tag, mode, per-file hashes) plus
// pristine copies of every managed file as the CLI wrote it. Hashes detect
// user edits before an upgrade overwrites a file; the pristine copies are the
// future base for a 3-way merge of user edits with upstream changes.
package state

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// FileName is the manifest's name inside the install root.
const FileName = "install-state.json"

// pristineDirName holds the as-written copies of managed files, keyed by
// their DestRel paths, inside the install root.
const pristineDirName = ".onyx-cli-pristine"

// SchemaVersion is the current manifest schema.
const SchemaVersion = 1

// Mode is the deployment mode recorded in the manifest.
type Mode string

const (
	ModeStandard Mode = "standard"
	ModeLite     Mode = "lite"
	ModeProd     Mode = "prod"
)

// FileEntry records one managed file as last written by the CLI.
type FileEntry struct {
	SHA256 string `json:"sha256"`
}

// Manifest is the persisted install state.
type Manifest struct {
	SchemaVersion int    `json:"schema_version"`
	InstalledTag  string `json:"installed_tag"`
	CLIVersion    string `json:"cli_version"`
	Mode          Mode   `json:"mode"`
	IncludeCraft  bool   `json:"include_craft"`
	// Project is the docker compose project name, when it differs from the
	// default pinned in docker-compose.yml (adopted deployments created under
	// another name keep it — renaming would strand their volumes).
	Project     string               `json:"project,omitempty"`
	Files       map[string]FileEntry `json:"files"` // keyed by DestRel
	InstalledAt time.Time            `json:"installed_at"`
	UpdatedAt   time.Time            `json:"updated_at"`
}

// Path returns the manifest location for an install root.
func Path(installRoot string) string {
	return filepath.Join(installRoot, FileName)
}

// Exists reports whether an install root carries a manifest, i.e. whether the
// CLI has ever managed it.
func Exists(installRoot string) bool {
	_, err := os.Stat(Path(installRoot))
	return err == nil
}

// Load reads the manifest from an install root. A missing manifest returns
// (nil, nil): the deployment predates the CLI (or was created by install.sh)
// and callers run their adopt flow.
func Load(installRoot string) (*Manifest, error) {
	data, err := os.ReadFile(Path(installRoot))
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("failed to read %s: %w", FileName, err)
	}
	var m Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("failed to parse %s: %w", FileName, err)
	}
	if m.SchemaVersion > SchemaVersion {
		return nil, fmt.Errorf("%s has schema version %d, written by a newer onyx-cli — upgrade the CLI",
			FileName, m.SchemaVersion)
	}
	return &m, nil
}

// Save atomically writes the manifest into an install root.
func (m *Manifest) Save(installRoot string) error {
	m.SchemaVersion = SchemaVersion
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to encode %s: %w", FileName, err)
	}
	data = append(data, '\n')

	tmp, err := os.CreateTemp(installRoot, FileName+".tmp-*")
	if err != nil {
		return fmt.Errorf("failed to create temp file for %s: %w", FileName, err)
	}
	tmpName := tmp.Name()
	defer func() { _ = os.Remove(tmpName) }()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("failed to write %s: %w", FileName, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("failed to close %s: %w", FileName, err)
	}
	if err := os.Rename(tmpName, Path(installRoot)); err != nil {
		return fmt.Errorf("failed to replace %s: %w", FileName, err)
	}
	return nil
}

// HashBytes returns the manifest-format digest of content.
func HashBytes(content []byte) string {
	sum := sha256.Sum256(content)
	return hex.EncodeToString(sum[:])
}

// HashFile returns the manifest-format digest of the file at path.
func HashFile(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return HashBytes(data), nil
}

// RecordFile stores content's hash for destRel and writes the pristine copy.
func (m *Manifest) RecordFile(installRoot, destRel string, content []byte) error {
	if m.Files == nil {
		m.Files = make(map[string]FileEntry)
	}
	m.Files[destRel] = FileEntry{SHA256: HashBytes(content)}

	path := pristinePath(installRoot, destRel)
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("failed to create pristine dir for %s: %w", destRel, err)
	}
	if err := os.WriteFile(path, content, 0644); err != nil {
		return fmt.Errorf("failed to write pristine copy of %s: %w", destRel, err)
	}
	return nil
}

// ForgetFile drops destRel from the manifest and removes its pristine copy
// (used when an overlay is removed, e.g. switching lite -> standard).
func (m *Manifest) ForgetFile(installRoot, destRel string) error {
	delete(m.Files, destRel)
	if err := os.Remove(pristinePath(installRoot, destRel)); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove pristine copy of %s: %w", destRel, err)
	}
	return nil
}

// Pristine returns the as-written copy of destRel, or (nil, nil) if none is
// stored.
func Pristine(installRoot, destRel string) ([]byte, error) {
	data, err := os.ReadFile(pristinePath(installRoot, destRel))
	if os.IsNotExist(err) {
		return nil, nil
	}
	return data, err
}

// UserEdited reports whether the on-disk file at destRel differs from the
// hash recorded in the manifest. Files absent from the manifest report true
// (no baseline means the CLI cannot vouch for them); files recorded but
// missing on disk report false (nothing to preserve).
func (m *Manifest) UserEdited(installRoot, destRel string) (bool, error) {
	entry, ok := m.Files[destRel]
	if !ok {
		return true, nil
	}
	onDisk, err := HashFile(filepath.Join(installRoot, filepath.FromSlash(destRel)))
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return onDisk != entry.SHA256, nil
}

func pristinePath(installRoot, destRel string) string {
	return filepath.Join(installRoot, pristineDirName, filepath.FromSlash(destRel))
}
