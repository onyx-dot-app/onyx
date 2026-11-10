// Package journal stores one durable JSON record per VM, so that a new agent
// process can re-adopt the VMs that are still running.
//
// Each record is <dir>/<sandbox_id>.json. A write goes to a temporary file,
// which is synced and then renamed over the record; the directory is synced
// after the rename. A crash therefore leaves either the old or the new record,
// never a partial one. Load ignores temporary files.
package journal

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// State is the state of a journaled VM.
type State string

const (
	// Starting: Create runs. The caller has not seen a result yet.
	Starting State = "starting"
	// Running: Create returned the VM.
	Running State = "running"
	// Stopped: Stop succeeded. The record is a tombstone for repeat Stops and
	// stale attempts.
	Stopped State = "stopped"
)

// Record is one VM.
type Record struct {
	SandboxID  string `json:"sandbox_id"`
	Attempt    uint64 `json:"attempt"`
	Generation uint64 `json:"generation"`
	State      State  `json:"state"`
	// PID is the host PID of Firecracker. PIDStart is its start time from
	// /proc/<pid>/stat (clock ticks since boot), to detect PID reuse.
	PID      int    `json:"pid"`
	PIDStart uint64 `json:"pid_start"`
	UID      uint32 `json:"uid"`
	// Chroot is the jailer chroot dir (<base>/firecracker/<id>).
	Chroot     string    `json:"chroot"`
	APISock    string    `json:"api_sock"`
	VsockUDS   string    `json:"vsock_uds"`
	Template   string    `json:"template"`
	VCPUs      uint32    `json:"vcpus"`
	MemMiB     uint32    `json:"mem_mib"`
	ScratchGiB uint32    `json:"scratch_gib"`
	StartedAt  time.Time `json:"started_at"`
	StoppedAt  time.Time `json:"stopped_at,omitzero"`
	TenantID   string    `json:"tenant_id,omitempty"`
	// Prev is the stopped attempt that a starting record replaces. A crash
	// during the start must not forget it.
	Prev *Tombstone `json:"prev,omitempty"`
}

// Tombstone is a stopped attempt.
type Tombstone struct {
	Attempt    uint64    `json:"attempt"`
	Generation uint64    `json:"generation"`
	StoppedAt  time.Time `json:"stopped_at"`
}

// BadFile is a record that could not be read. Its VM must be left alone.
type BadFile struct {
	SandboxID string
	Path      string
	Err       error
}

var nameRE = regexp.MustCompile(`^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.json$`)

// Journal is the record directory.
type Journal struct {
	Dir string
}

// Path returns the record file of id.
func (j *Journal) Path(id string) string { return filepath.Join(j.Dir, id+".json") }

// Write stores rec atomically.
func (j *Journal) Write(rec Record) error {
	if !nameRE.MatchString(rec.SandboxID + ".json") {
		return fmt.Errorf("journal: bad sandbox id %q", rec.SandboxID)
	}
	raw, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(j.Dir, "."+rec.SandboxID+".*.tmp")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := tmp.Write(append(raw, '\n')); err != nil {
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
	if err := os.Rename(tmp.Name(), j.Path(rec.SandboxID)); err != nil {
		return err
	}
	return j.syncDir()
}

// Remove deletes the record of id. A missing record is not an error.
func (j *Journal) Remove(id string) error {
	if err := os.Remove(j.Path(id)); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	return j.syncDir()
}

// Load reads every record. Records that cannot be read or parsed are
// returned in bad. Temporary files from an interrupted write are removed.
func (j *Journal) Load() (recs []Record, bad []BadFile, err error) {
	entries, err := os.ReadDir(j.Dir)
	if err != nil {
		return nil, nil, err
	}
	for _, e := range entries {
		name := e.Name()
		if strings.HasPrefix(name, ".") && strings.HasSuffix(name, ".tmp") {
			_ = os.Remove(filepath.Join(j.Dir, name))
			continue
		}
		m := nameRE.FindStringSubmatch(name)
		if m == nil {
			continue
		}
		p := filepath.Join(j.Dir, name)
		raw, readErr := os.ReadFile(p)
		if readErr != nil {
			bad = append(bad, BadFile{SandboxID: m[1], Path: p, Err: readErr})
			continue
		}
		var r Record
		if parseErr := json.Unmarshal(raw, &r); parseErr != nil {
			bad = append(bad, BadFile{SandboxID: m[1], Path: p, Err: parseErr})
			continue
		}
		if r.SandboxID != m[1] {
			bad = append(bad, BadFile{SandboxID: m[1], Path: p, Err: fmt.Errorf("record names sandbox %q", r.SandboxID)})
			continue
		}
		switch r.State {
		case Starting, Running, Stopped:
		default:
			bad = append(bad, BadFile{SandboxID: m[1], Path: p, Err: fmt.Errorf("unknown state %q", r.State)})
			continue
		}
		recs = append(recs, r)
	}
	return recs, bad, nil
}

func (j *Journal) syncDir() error {
	d, err := os.Open(j.Dir)
	if err != nil {
		return err
	}
	defer func() { _ = d.Close() }()
	return d.Sync()
}
