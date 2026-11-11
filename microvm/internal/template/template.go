// Package template reads, checks and removes the VM templates on a node.
//
// A template is a Firecracker snapshot in <store>/<version>/:
//
//	manifest.json  Manifest (key, file hashes, snapshot hash)
//	rootfs.ext4    read-only root drive        (drive "rootfs",   /dev/vda)
//	scratch.ext4   empty scratch drive          (drive "scratch",  /dev/vdb)
//	managed.ext4   empty read-only managed drive (drive "managed", /dev/vdc)
//	upload-a.ext4  read-only upload slot A      (drive "upload_a", /dev/vdd)
//	upload-b.ext4  read-only upload slot B      (drive "upload_b", /dev/vde)
//	managed-b.ext4 read-only managed slot B     (drive "managed_b", /dev/vdf; layout 3)
//
// Layout 4 has the same files and adds the balloon device (Balloon) to the
// template VM. Firecracker sets the balloon only before boot, and a restore
// keeps it.
//
//	vmstate        snapshot state
//	mem            snapshot memory
//
// The snapshot is taken inside a jailer chroot, so the drive paths in vmstate
// are /<file> and the vsock UDS is /v.sock. Every VM chroot has the same
// layout, with its own reflink copy of each file.
//
// Firecracker does not check that a snapshot fits the host, the kernel or
// the disks. The agent does: before every restore, the template key must
// match the node (CheckNode) and the files must match the manifest hashes
// (Store.Verify).
package template

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// LayoutVersion is the version of the template layout that the agent
// builds: the file names, the drive slots and their order. Layout 3 adds
// managed slot B (the spare for a managed drive swap) as the last drive, so
// the guest devices of the older slots do not move. The agent still restores
// layout 2 templates; their VMs cannot swap the managed drive. Layout 4
// adds the balloon device with free page reporting (ENG-4569); VMs of older
// layouts never return free memory to the node.
const LayoutVersion = 4

// OldestLayout is the oldest layout that the agent restores.
const OldestLayout = 2

// File names in a template directory and in each VM chroot.
const (
	ManifestFile = "manifest.json"
	RootfsFile   = "rootfs.ext4"
	ScratchFile  = "scratch.ext4"
	ManagedFile  = "managed.ext4"
	UploadAFile  = "upload-a.ext4"
	UploadBFile  = "upload-b.ext4"
	ManagedBFile = "managed-b.ext4"
	VMStateFile  = "vmstate"
	MemFile      = "mem"
)

// Drive IDs, the vsock UDS path and the guest CID that the snapshot uses.
const (
	RootfsDriveID  = "rootfs"
	ScratchDriveID = "scratch"
	ManagedDriveID = "managed"
	UploadADriveID = "upload_a"
	UploadBDriveID = "upload_b"
	// ManagedBDriveID is managed slot B. Slot A is ManagedDriveID.
	ManagedBDriveID = "managed_b"
	VsockUDS        = "/v.sock"
	GuestCID        = 3
)

// Drive is one drive slot of the template.
type Drive struct {
	ID       string
	File     string
	ReadOnly bool
}

// layoutDrives are the drive slots of each layout in guest order (vda, vdb,
// ...). The guest finds its drives by this order.
var layoutDrives = map[int][]Drive{
	2: {
		{RootfsDriveID, RootfsFile, true},
		{ScratchDriveID, ScratchFile, false},
		{ManagedDriveID, ManagedFile, true},
		{UploadADriveID, UploadAFile, true},
		{UploadBDriveID, UploadBFile, true},
	},
	3: {
		{RootfsDriveID, RootfsFile, true},
		{ScratchDriveID, ScratchFile, false},
		{ManagedDriveID, ManagedFile, true},
		{UploadADriveID, UploadAFile, true},
		{UploadBDriveID, UploadBFile, true},
		{ManagedBDriveID, ManagedBFile, true},
	},
	4: {
		{RootfsDriveID, RootfsFile, true},
		{ScratchDriveID, ScratchFile, false},
		{ManagedDriveID, ManagedFile, true},
		{UploadADriveID, UploadAFile, true},
		{UploadBDriveID, UploadBFile, true},
		{ManagedBDriveID, ManagedBFile, true},
	},
}

// BalloonLayout is the first layout whose template VM has the balloon.
const BalloonLayout = 4

// BalloonConfig is the Firecracker balloon device of a template VM.
type BalloonConfig struct {
	AmountMiB         int64
	DeflateOnOOM      bool
	StatsIntervalS    int64
	FreePageReporting bool
	FreePageHinting   bool
}

// Balloon is the balloon of layout 4 templates (results/mem.md): free page
// reporting returns the pages that the guest frees, so the node sees the
// real use. The balloon never inflates (amount 0): a VM that works against
// an inflated balloon is many times slower. Free page hinting is a
// Firecracker developer preview with a memory corruption race, so it is
// off. Statistics are on, because Firecracker can turn them on later only
// if they were on at boot.
var Balloon = BalloonConfig{AmountMiB: 0, DeflateOnOOM: true, StatsIntervalS: 5, FreePageReporting: true}

// BalloonFor returns the balloon of a layout, or nil for a layout without one.
func BalloonFor(layout int) *BalloonConfig {
	if layout < BalloonLayout || !SupportedLayout(layout) {
		return nil
	}
	b := Balloon
	return &b
}

// DrivesFor returns the drive slots of a layout, or nil for a layout that
// the agent does not restore.
func DrivesFor(layout int) []Drive { return layoutDrives[layout] }

// FilesFor returns the data files of a layout, in manifest order: the drive
// files, then vmstate and mem.
func FilesFor(layout int) []string {
	ds := layoutDrives[layout]
	if ds == nil {
		return nil
	}
	out := make([]string, 0, len(ds)+2)
	for _, d := range ds {
		out = append(out, d.File)
	}
	return append(out, VMStateFile, MemFile)
}

// SupportedLayout reports whether the agent restores templates of layout v.
func SupportedLayout(v int) bool { return layoutDrives[v] != nil }

// Drives are the drive slots of the layout that the agent builds.
var Drives = DrivesFor(LayoutVersion)

// Files are the data files of the layout that the agent builds.
var Files = FilesFor(LayoutVersion)

// snapshotFiles are the files that the snapshot hash covers first. A
// mismatched memory and vmstate pair, or another root drive, breaks a
// restored VM without an error from Firecracker.
var snapshotFiles = []string{VMStateFile, MemFile, RootfsFile}

var versionRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

// Key is everything that a template depends on. A template is only valid on
// a node whose NodeKey matches its key.
type Key struct {
	// Source image of the root drive (from the rootfs manifest).
	ImageRef    string `json:"image_ref"`
	ImageDigest string `json:"image_digest"`
	// SHA256 of rootfs.ext4 and of the rootfs manifest.json.
	RootfsSHA256         string `json:"rootfs_sha256"`
	RootfsManifestSHA256 string `json:"rootfs_manifest_sha256"`
	// Guest kernel (vmlinux) release and SHA256.
	GuestKernel       string `json:"guest_kernel"`
	GuestKernelSHA256 string `json:"guest_kernel_sha256"`
	// Host side: Firecracker version, CPU model, host kernel release.
	FirecrackerVersion string `json:"firecracker_version"`
	CPUModel           string `json:"cpu_model"`
	HostKernel         string `json:"host_kernel"`
	// SHA256 fingerprint of the egress CA in the root drive. Empty: the root
	// drive has no CA (the guest daemon installs it at Init).
	CAFingerprint string `json:"ca_fingerprint"`
	LayoutVersion int    `json:"layout_version"`
	BootArgs      string `json:"boot_args"`
	VCPUs         uint32 `json:"vcpus"`
	MemMiB        uint32 `json:"mem_mib"`
	ScratchGiB    uint32 `json:"scratch_gib"`
}

// Hash returns the SHA256 of the key's JSON form.
func (k Key) Hash() string {
	raw, err := json.Marshal(k)
	if err != nil {
		panic(err) // a struct of strings and numbers always marshals
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// NodeKey is the part of the key that the node decides.
type NodeKey struct {
	FirecrackerVersion string
	CPUModel           string
	HostKernel         string
	GuestKernelSHA256  string
	// CAFingerprint is the egress CA of this deployment. Empty: not checked.
	CAFingerprint string
	// RootfsCARequired: the agent has no CA source, so a template whose root
	// drive has no CA does not fit (its VMs would trust no egress CA).
	RootfsCARequired bool
}

// NoCAError is the reason that a CA-free root drive does not fit an agent
// with no CA source.
const NoCAError = "egress CA: the root drive has none and the agent has no --egress-ca or --egress-ca-configmap"

// CheckNode returns TEMPLATE_INCOMPATIBLE if the key does not fit node n.
func (k Key) CheckNode(n NodeKey) error {
	var bad []string
	add := func(what, tpl, node string) {
		if tpl != node {
			bad = append(bad, fmt.Sprintf("%s %q (node %q)", what, tpl, node))
		}
	}
	if !SupportedLayout(k.LayoutVersion) {
		bad = append(bad, fmt.Sprintf("layout version %d (agent %d to %d)", k.LayoutVersion, OldestLayout, LayoutVersion))
	}
	add("firecracker", k.FirecrackerVersion, n.FirecrackerVersion)
	add("cpu model", k.CPUModel, n.CPUModel)
	add("host kernel", k.HostKernel, n.HostKernel)
	add("guest kernel sha256", k.GuestKernelSHA256, n.GuestKernelSHA256)
	// A template with no CA in its root drive fits every CA.
	if n.CAFingerprint != "" && k.CAFingerprint != "" {
		add("egress CA", k.CAFingerprint, n.CAFingerprint)
	}
	if n.RootfsCARequired && k.CAFingerprint == "" {
		bad = append(bad, NoCAError)
	}
	if len(bad) > 0 {
		return apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE, "template does not fit this node: %s", strings.Join(bad, ", "))
	}
	return nil
}

// Manifest describes one template.
type Manifest struct {
	Schema  int    `json:"schema"`
	Version string `json:"version"`
	Key     `json:"key"`
	// KeySHA256 is Key.Hash().
	KeySHA256 string `json:"key_sha256"`
	// Files maps each file in Files to its SHA256.
	Files map[string]string `json:"files"`
	// SnapshotSHA256 is the hash over (vmstate, mem, rootfs) and then the
	// other drive files (SnapshotHash).
	SnapshotSHA256 string    `json:"snapshot_sha256"`
	BuiltAt        time.Time `json:"built_at"`
	BuildMS        int64     `json:"build_ms"`
}

// SnapshotHash hashes the file hashes: first vmstate, mem and rootfs, then
// the other files of the layout in manifest order, with the key hash.
func SnapshotHash(layout int, keySHA string, files map[string]string) string {
	h := sha256.New()
	_, _ = fmt.Fprintf(h, "key %s\n", keySHA)
	seen := map[string]bool{}
	for _, f := range append(append([]string{}, snapshotFiles...), FilesFor(layout)...) {
		if seen[f] {
			continue
		}
		seen[f] = true
		_, _ = fmt.Fprintf(h, "%s %s\n", f, files[f])
	}
	return hex.EncodeToString(h.Sum(nil))
}

// check verifies the manifest's own hashes and fields.
func (m *Manifest) check(version string) error {
	if !SupportedLayout(m.Schema) || m.LayoutVersion != m.Schema {
		return fmt.Errorf("manifest schema %d (layout %d), the agent reads %d to %d", m.Schema, m.LayoutVersion, OldestLayout, LayoutVersion)
	}
	files := FilesFor(m.Schema)
	if m.Version != version {
		return fmt.Errorf("manifest has version %q", m.Version)
	}
	if m.VCPUs == 0 || m.MemMiB == 0 || m.ScratchGiB == 0 {
		return errors.New("manifest has a zero vcpus, mem_mib or scratch_gib")
	}
	if m.KeySHA256 != m.Hash() {
		return errors.New("manifest key_sha256 does not match its key")
	}
	for _, f := range files {
		if len(m.Files[f]) != sha256.Size*2 {
			return fmt.Errorf("manifest has no SHA256 for %s", f)
		}
	}
	if len(m.Files) != len(files) {
		return fmt.Errorf("manifest lists %d files, want %d", len(m.Files), len(files))
	}
	if m.SnapshotSHA256 != SnapshotHash(m.Schema, m.KeySHA256, m.Files) {
		return errors.New("manifest snapshot_sha256 does not match its file hashes")
	}
	if m.Files[RootfsFile] != m.RootfsSHA256 {
		return errors.New("manifest rootfs hash differs from its key")
	}
	return nil
}

// Template is a manifest and its directory.
type Template struct {
	Manifest
	Dir string
	// prints are the file fingerprints at the last full verification.
	prints map[string]fingerprint
}

// Path returns the path of a file in the template directory.
func (t *Template) Path(name string) string { return filepath.Join(t.Dir, name) }

// FileList returns the data files of the template's layout.
func (t *Template) FileList() []string { return FilesFor(t.LayoutVersion) }

// ManagedSlots returns the number of managed drive slots: 2 from layout 3
// on (a VM can swap its managed drive), else 1.
func (t *Template) ManagedSlots() int {
	for _, d := range DrivesFor(t.LayoutVersion) {
		if d.ID == ManagedBDriveID {
			return 2
		}
	}
	return 1
}

// HasBalloon reports whether the template's VMs have the balloon device.
func (t *Template) HasBalloon() bool { return BalloonFor(t.LayoutVersion) != nil }

// CheckUnchanged fails if a file changed since Store.Verify hashed it. Call
// it after the files are copied, so the copies are the verified content.
func (t *Template) CheckUnchanged() error {
	if t.prints == nil {
		return apierr.New(pb.ErrorReason_INTERNAL, "template %q was not verified", t.Version)
	}
	for _, f := range t.FileList() {
		got, err := statPrint(t.Path(f))
		if err != nil || got != t.prints[f] {
			return apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE,
				"template %q file %s changed after its hash check", t.Version, f)
		}
	}
	return nil
}

// Store is the template directory of a node.
type Store struct {
	Dir string

	mu sync.Mutex
	// verified holds the fingerprints of templates whose hashes were checked.
	verified map[string]verifiedPrints
	// locks serialize the full hash check per template.
	locks map[string]*sync.Mutex

	// removeMu orders Pin with the in-use check and removal in
	// RemoveUnused and GC.
	removeMu sync.Mutex
	pins     map[string]int
}

// verifiedPrints are the file fingerprints of a full hash check and the
// snapshot hash of the manifest that the check compared with.
type verifiedPrints struct {
	prints   map[string]fingerprint
	snapshot string
}

// ValidVersion reports whether v is a safe template version name.
func ValidVersion(v string) bool { return versionRE.MatchString(v) }

// Get loads one template and checks its manifest. It does not hash the
// files (Verify does).
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
		return nil, apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE, "template %q manifest: %v", version, err)
	}
	if err := m.check(version); err != nil {
		return nil, apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE, "template %q: %v", version, err)
	}
	for _, f := range FilesFor(m.Schema) {
		st, err := os.Lstat(filepath.Join(dir, f))
		if err != nil {
			return nil, apierr.New(pb.ErrorReason_TEMPLATE_MISSING, "template %q has no %s: %v", version, f, err)
		}
		if !st.Mode().IsRegular() {
			return nil, apierr.New(pb.ErrorReason_TEMPLATE_MISSING, "template %q %s is not a regular file", version, f)
		}
	}
	return &Template{Manifest: m, Dir: dir}, nil
}

// Verify checks that every file has the SHA256 in the manifest. The full
// hash runs once per template; later calls compare the file fingerprints
// (inode, size, mtime, ctime) with the ones of the last full check, and hash
// again if one changed. On success, t can CheckUnchanged.
func (s *Store) Verify(t *Template) error {
	lock := s.lock(t.Version)
	lock.Lock()
	defer lock.Unlock()

	files := t.FileList()
	prints := map[string]fingerprint{}
	for _, f := range files {
		p, err := statPrint(t.Path(f))
		if err != nil {
			return apierr.New(pb.ErrorReason_TEMPLATE_MISSING, "template %q %s: %v", t.Version, f, err)
		}
		prints[f] = p
	}
	s.mu.Lock()
	cached := s.verified[t.Version]
	s.mu.Unlock()
	if cached.snapshot == t.SnapshotSHA256 && samePrints(cached.prints, prints) {
		t.prints = prints
		return nil
	}
	sums, err := HashFiles(t.Dir, files)
	if err != nil {
		return fmt.Errorf("hash template %q: %w", t.Version, err)
	}
	for _, f := range files {
		if sums[f] != t.Files[f] {
			s.forget(t.Version)
			return apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE,
				"template %q file %s has SHA256 %s, the manifest has %s", t.Version, f, sums[f], t.Files[f])
		}
	}
	// A file that changed during the hash is not verified.
	for _, f := range files {
		p, err := statPrint(t.Path(f))
		if err != nil || p != prints[f] {
			s.forget(t.Version)
			return apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE, "template %q file %s changed during its hash check", t.Version, f)
		}
	}
	s.mu.Lock()
	if s.verified == nil {
		s.verified = map[string]verifiedPrints{}
	}
	s.verified[t.Version] = verifiedPrints{prints: prints, snapshot: t.SnapshotSHA256}
	s.mu.Unlock()
	t.prints = prints
	return nil
}

func (s *Store) lock(version string) *sync.Mutex {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.locks == nil {
		s.locks = map[string]*sync.Mutex{}
	}
	l := s.locks[version]
	if l == nil {
		l = &sync.Mutex{}
		s.locks[version] = l
	}
	return l
}

func (s *Store) forget(version string) {
	s.mu.Lock()
	delete(s.verified, version)
	s.mu.Unlock()
}

func samePrints(a, b map[string]fingerprint) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range b {
		if a[k] != v {
			return false
		}
	}
	return true
}

// List returns every template with a valid manifest, sorted by version. It
// skips directories that are not complete templates.
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

// Pin keeps version from RemoveUnused and GC until the returned func runs.
// A restore pins its template from before Get until its VM is in the table
// that inUse reports.
func (s *Store) Pin(version string) func() {
	s.removeMu.Lock()
	defer s.removeMu.Unlock()
	if s.pins == nil {
		s.pins = map[string]int{}
	}
	s.pins[version]++
	var once sync.Once
	return func() {
		once.Do(func() {
			s.removeMu.Lock()
			defer s.removeMu.Unlock()
			if s.pins[version]--; s.pins[version] <= 0 {
				delete(s.pins, version)
			}
		})
	}
}

// Exists reports whether the template directory is there, complete or not.
func (s *Store) Exists(version string) (bool, error) {
	if !ValidVersion(version) {
		return false, fmt.Errorf("invalid template version %q", version)
	}
	_, err := os.Lstat(filepath.Join(s.Dir, version))
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	return err == nil, err
}

// RemoveUnused deletes one template directory unless it is pinned or
// inUse() has it. inUse runs after the pins are frozen, so a VM that
// released its pin is in inUse. It returns false if the template is kept.
func (s *Store) RemoveUnused(version string, inUse func() map[string]bool) (bool, error) {
	if !ValidVersion(version) {
		return false, fmt.Errorf("invalid template version %q", version)
	}
	s.removeMu.Lock()
	defer s.removeMu.Unlock()
	if s.pins[version] > 0 || inUse()[version] {
		return false, nil
	}
	return true, s.removeLocked(version)
}

func (s *Store) removeLocked(version string) error {
	s.forget(version)
	return os.RemoveAll(filepath.Join(s.Dir, version))
}

// GC keeps the keep newest valid templates (by build time), every pinned
// template and every template in inUse(). It removes the other template
// directories, also ones with a manifest that the agent cannot read (an
// older layout), and returns their names. Hidden directories (builds in
// progress) are not touched.
func (s *Store) GC(keep int, inUse func() map[string]bool) ([]string, error) {
	s.removeMu.Lock()
	defer s.removeMu.Unlock()
	used := inUse()
	entries, err := os.ReadDir(s.Dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	type cand struct {
		name  string
		built time.Time
		valid bool
	}
	var cands []cand
	for _, e := range entries {
		if !e.IsDir() || !ValidVersion(e.Name()) {
			continue
		}
		c := cand{name: e.Name()}
		if t, err := s.Get(e.Name()); err == nil {
			c.built, c.valid = t.BuiltAt, true
		}
		cands = append(cands, c)
	}
	// Newest first; invalid ones last.
	sort.SliceStable(cands, func(i, j int) bool {
		if cands[i].valid != cands[j].valid {
			return cands[i].valid
		}
		if !cands[i].built.Equal(cands[j].built) {
			return cands[i].built.After(cands[j].built)
		}
		return cands[i].name > cands[j].name
	})
	var removed []string
	kept := 0
	for _, c := range cands {
		if c.valid && kept < keep {
			kept++
			continue
		}
		if used[c.name] || s.pins[c.name] > 0 {
			continue
		}
		if err := s.removeLocked(c.name); err != nil {
			return removed, fmt.Errorf("remove template %s: %w", c.name, err)
		}
		removed = append(removed, c.name)
	}
	return removed, nil
}

// Prints are the file fingerprints of a sealed template.
type Prints map[string]fingerprint

// Seal hashes the files in dir and writes the manifest for m (Version and
// Key set by the caller) with Schema, KeySHA256, Files and SnapshotSHA256
// filled in. known holds SHA256 sums the caller already has (it may be nil).
// It returns the manifest and the file fingerprints from before the hash,
// for MarkVerified. The layout is m.LayoutVersion, or LayoutVersion if it is
// zero.
func Seal(dir string, m Manifest, known map[string]string) (Manifest, Prints, error) {
	layout := m.LayoutVersion
	if layout == 0 {
		layout = LayoutVersion
	}
	files := FilesFor(layout)
	if files == nil {
		return m, nil, fmt.Errorf("layout %d is not supported", layout)
	}
	prints := Prints{}
	for _, f := range files {
		p, err := statPrint(filepath.Join(dir, f))
		if err != nil {
			return m, nil, err
		}
		prints[f] = p
	}
	var todo []string
	for _, f := range files {
		if known[f] == "" {
			todo = append(todo, f)
		}
	}
	sums, err := HashFiles(dir, todo)
	if err != nil {
		return m, nil, err
	}
	for _, f := range files {
		if known[f] != "" {
			sums[f] = known[f]
		}
	}
	m.Schema = layout
	m.LayoutVersion = layout
	m.RootfsSHA256 = sums[RootfsFile]
	m.KeySHA256 = m.Hash()
	m.Files = sums
	m.SnapshotSHA256 = SnapshotHash(layout, m.KeySHA256, sums)
	return m, prints, WriteManifest(dir, m)
}

// MarkVerified records that the template's files are the ones Seal hashed,
// if their fingerprints did not change since then (a directory rename keeps
// them). Then Verify does not hash them again.
func (s *Store) MarkVerified(t *Template, prints Prints) error {
	for _, f := range t.FileList() {
		p, err := statPrint(t.Path(f))
		if err != nil {
			return err
		}
		if p != prints[f] {
			return fmt.Errorf("template %q file %s changed after it was sealed", t.Version, f)
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.verified == nil {
		s.verified = map[string]verifiedPrints{}
	}
	s.verified[t.Version] = verifiedPrints{prints: prints, snapshot: t.SnapshotSHA256}
	return nil
}

// WriteManifest writes m to dir atomically.
func WriteManifest(dir string, m Manifest) error {
	raw, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	tmp := filepath.Join(dir, ManifestFile+".tmp")
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(append(raw, '\n')); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(dir, ManifestFile))
}
