package coverage

import (
	"bytes"
	"fmt"
	"os"
	"regexp"
	"sort"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/s3"
	"gopkg.in/yaml.v3"
)

// SnapshotVersion is the format version written into every snapshot. A reader
// refuses a version it does not know, so a format change fails loudly.
const SnapshotVersion = 1

// snapshotHeader is written above the generated content so a reader of the
// file knows how it is maintained.
const snapshotHeader = `# Statement coverage recorded by ` + "`ods coverage --publish`" + ` for one commit.
#
# Generated file: do not edit by hand.
`

// commitPattern is a full git object name, which is what a snapshot is keyed by.
var commitPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)

// SnapshotPackage holds the exact statement counts for one package.
type SnapshotPackage struct {
	Covered    int `yaml:"covered"`
	Statements int `yaml:"statements"`
}

// Snapshot is the exact coverage measured for one commit of one module. Unlike
// a Baseline it records counts, not floors, so a comparison against it is exact.
type Snapshot struct {
	Version int `yaml:"version"`
	// Commit is the full 40-hex SHA the counts were measured at.
	Commit string `yaml:"commit"`
	// Module is the module directory relative to the git root, e.g. "tools/ods".
	Module string `yaml:"module"`
	// Packages maps a module-relative package path to its counts.
	Packages map[string]SnapshotPackage `yaml:"packages"`
}

// NewSnapshot records a measured profile as the snapshot of a commit. The
// counts are kept exactly, so a later comparison is exact.
func NewSnapshot(profile *Profile, commit, module string) *Snapshot {
	snapshot := &Snapshot{
		Version:  SnapshotVersion,
		Commit:   commit,
		Module:   module,
		Packages: make(map[string]SnapshotPackage, len(profile.Packages)),
	}
	for _, pkg := range profile.Packages {
		snapshot.Packages[pkg.Package] = SnapshotPackage{
			Covered:    pkg.Covered,
			Statements: pkg.Total,
		}
	}
	return snapshot
}

// ParseSnapshot reads a snapshot from its YAML form. An unknown field is an
// error: a snapshot the reader does not fully understand must not be trusted.
func ParseSnapshot(data []byte) (*Snapshot, error) {
	decoder := yaml.NewDecoder(bytes.NewReader(data))
	decoder.KnownFields(true)

	var snapshot Snapshot
	if err := decoder.Decode(&snapshot); err != nil {
		return nil, fmt.Errorf("parse coverage snapshot: %w", err)
	}
	if snapshot.Packages == nil {
		snapshot.Packages = map[string]SnapshotPackage{}
	}
	if err := snapshot.validate(); err != nil {
		return nil, err
	}
	return &snapshot, nil
}

// validate rejects a snapshot that cannot describe a real measurement. A
// comparison against a broken snapshot would silently report nonsense.
func (s *Snapshot) validate() error {
	if s.Version != SnapshotVersion {
		return fmt.Errorf("coverage snapshot version must be %d, got %d", SnapshotVersion, s.Version)
	}
	if !commitPattern.MatchString(s.Commit) {
		return fmt.Errorf("coverage snapshot commit must be a full 40-hex sha, got %q", s.Commit)
	}
	if s.Module == "" {
		return fmt.Errorf("coverage snapshot module must not be empty")
	}
	for name, pkg := range s.Packages {
		if name == "" {
			return fmt.Errorf("coverage snapshot has a package with an empty name")
		}
		if pkg.Covered < 0 || pkg.Statements < 0 {
			return fmt.Errorf("coverage snapshot counts for %s must not be negative, got %d/%d",
				name, pkg.Covered, pkg.Statements)
		}
		if pkg.Covered > pkg.Statements {
			return fmt.Errorf("coverage snapshot for %s covers %d of %d statements",
				name, pkg.Covered, pkg.Statements)
		}
	}
	return nil
}

// Encode renders the snapshot as YAML. yaml.v3 sorts map keys, so the output
// is stable across runs.
func (s *Snapshot) Encode() ([]byte, error) {
	var body bytes.Buffer
	body.WriteString(snapshotHeader)

	encoder := yaml.NewEncoder(&body)
	encoder.SetIndent(2)
	if err := encoder.Encode(s); err != nil {
		return nil, fmt.Errorf("encode coverage snapshot: %w", err)
	}
	if err := encoder.Close(); err != nil {
		return nil, fmt.Errorf("encode coverage snapshot: %w", err)
	}
	return body.Bytes(), nil
}

// LoadSnapshotFile reads a snapshot from disk.
func LoadSnapshotFile(path string) (*Snapshot, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	snapshot, err := ParseSnapshot(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return snapshot, nil
}

// SaveFile writes the snapshot to disk.
func (s *Snapshot) SaveFile(path string) error {
	data, err := s.Encode()
	if err != nil {
		return err
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	return nil
}

// Profile rebuilds the measured profile, so percentages come from the same
// code that computes them for a live run.
func (s *Snapshot) Profile() *Profile {
	profile := &Profile{Packages: make([]PackageCoverage, 0, len(s.Packages))}
	for name, pkg := range s.Packages {
		profile.Packages = append(profile.Packages, PackageCoverage{
			Package: name,
			Covered: pkg.Covered,
			Total:   pkg.Statements,
		})
	}
	sort.Slice(profile.Packages, func(i, j int) bool {
		return profile.Packages[i].Package < profile.Packages[j].Package
	})
	return profile
}

// Reference makes the snapshot the target of a comparison.
func (s *Snapshot) Reference() *Reference {
	profile := s.Profile()
	reference := &Reference{
		Kind:     ReferenceBase,
		Label:    ShortCommit(s.Commit),
		Total:    profile.Total(),
		Packages: make(map[string]float64, len(profile.Packages)),
	}
	for _, pkg := range profile.Packages {
		reference.Packages[pkg.Package] = pkg.Percent()
	}
	return reference
}

// ShortCommit abbreviates a commit for a report.
func ShortCommit(sha string) string {
	if len(sha) < 7 {
		return sha
	}
	return sha[:7]
}

// SnapshotObjectKey is where the snapshot of one commit of one module lives in
// the bucket.
func SnapshotObjectKey(module, commit string) string {
	return "coverage/" + s3.SanitizeKeySegment(module) + "/" + commit + ".yaml"
}
