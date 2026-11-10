package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// DrainStatus is the drain state of the node (ENG-4569). The node drains
// while the manual flag is set or while it has a drain taint. A draining
// node refuses new VMs; the api_server saves and stops the running ones.
type DrainStatus struct {
	State  pb.DrainState
	Manual bool
	// Taints are the drain taints from the last node read that worked.
	Taints []string
	// Since is when the drain started; zero while the node is active.
	Since time.Time
	// WatchError is the error of the last node read, if it failed.
	WatchError string
}

type drainState struct {
	manual   bool
	taints   []string
	watchErr string
	since    time.Time
	// path keeps the manual flag across agent restarts. Empty: memory only.
	path string
}

type drainFile struct {
	Manual bool      `json:"manual"`
	Since  time.Time `json:"since"`
}

func (d *drainState) draining() bool { return d.manual || len(d.taints) > 0 }

// UseDrainFile keeps the manual drain flag in path and loads it. Call it
// before the API serves.
func (m *Manager) UseDrainFile(path string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.drain.path = path
	raw, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	var f drainFile
	if err := json.Unmarshal(raw, &f); err != nil {
		return fmt.Errorf("read %s: %w", path, err)
	}
	if f.Manual {
		m.drain.manual, m.drain.since = true, f.Since
		m.log.Warn("node is draining: the manual drain flag is set", "since", f.Since)
	}
	return nil
}

// SetDrain sets or clears the manual drain flag and returns the new state.
// The flag is written to disk before it applies.
func (m *Manager) SetDrain(manual bool) (DrainStatus, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	was := m.drain.draining()
	since := m.drain.since
	if manual && !was {
		since = m.now()
	}
	if m.drain.path != "" {
		if err := writeDrainFile(m.drain.path, drainFile{Manual: manual, Since: since}); err != nil {
			return DrainStatus{}, apierr.New(pb.ErrorReason_INTERNAL, "save the drain flag: %v", err)
		}
	}
	m.drain.manual = manual
	if manual && !was {
		m.drain.since = since
	}
	m.updateSinceLocked(was)
	m.log.Info("manual drain flag", "drain", manual, "draining", m.drain.draining(), "taints", m.drain.taints)
	return m.drainStatusLocked(), nil
}

// SetNodeDrain applies one read of the node: its drain taints, or the read
// error. After an error the taints of the last read that worked stay.
func (m *Manager) SetNodeDrain(taints []string, readErr error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if readErr != nil {
		if m.drain.watchErr == "" {
			m.log.Error("read the node for drain taints", "err", readErr)
		}
		m.drain.watchErr = readErr.Error()
		return
	}
	if m.drain.watchErr != "" {
		m.log.Info("node read works again")
		m.drain.watchErr = ""
	}
	taints = slices.Clone(taints)
	slices.Sort(taints)
	if slices.Equal(taints, m.drain.taints) {
		return
	}
	was := m.drain.draining()
	m.drain.taints = taints
	m.updateSinceLocked(was)
	m.log.Warn("node drain taints changed", "taints", taints, "draining", m.drain.draining())
}

func (m *Manager) updateSinceLocked(was bool) {
	switch now := m.drain.draining(); {
	case now && !was:
		if m.drain.since.IsZero() {
			m.drain.since = m.now()
		}
	case !now:
		m.drain.since = time.Time{}
	}
}

// Drain returns the drain state of the node.
func (m *Manager) Drain() DrainStatus {
	m.rescanForDrain()
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.drainStatusLocked()
}

func (m *Manager) drainStatusLocked() DrainStatus {
	s := DrainStatus{
		State: pb.DrainState_DRAIN_STATE_ACTIVE, Manual: m.drain.manual, Taints: slices.Clone(m.drain.taints),
		WatchError: m.drain.watchErr,
	}
	if m.drain.draining() {
		s.State, s.Since = pb.DrainState_DRAIN_STATE_DRAINED, m.drain.since
		// Kept processes in doubt, build VMs, and a scan that never worked
		// (their processes are unknown) also hold the drain.
		if m.liveVMsLocked() > 0 || len(m.doubt) > 0 || len(m.building) > 0 || m.needScan {
			s.State = pb.DrainState_DRAIN_STATE_DRAINING
		}
	}
	return s
}

// rescanForDrain scans the processes again while a draining node keeps
// processes in doubt or has no scan that worked, so a doubt whose process
// exited stops holding the drain.
func (m *Manager) rescanForDrain() {
	m.mu.Lock()
	need := m.drain.draining() && (len(m.doubt) > 0 || m.needScan)
	m.mu.Unlock()
	if !need || m.adopter == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := m.rescan(ctx); err != nil {
		m.log.Error("process scan for the drain state failed", "err", err)
	}
}

// drainErrLocked refuses a new VM on a draining node.
func (m *Manager) drainErrLocked() error {
	if !m.drain.draining() {
		return nil
	}
	var why []string
	if m.drain.manual {
		why = append(why, "the manual drain flag is set")
	}
	if len(m.drain.taints) > 0 {
		why = append(why, "the node has drain taints "+strings.Join(m.drain.taints, ", "))
	}
	e := apierr.New(pb.ErrorReason_NODE_DRAINING, "the node is draining since %s: %s",
		m.drain.since.UTC().Format(time.RFC3339), strings.Join(why, "; "))
	e.Metadata = map[string]string{
		"manual": fmt.Sprint(m.drain.manual), "taints": strings.Join(m.drain.taints, ","),
	}
	return e
}

// liveVMsLocked counts the VMs that are starting or running.
func (m *Manager) liveVMsLocked() int {
	n := 0
	for _, e := range m.vms {
		if e.vm.State != pb.VMState_VM_STATE_EXITED {
			n++
		}
	}
	return n
}

func writeDrainFile(path string, f drainFile) error {
	raw, err := json.Marshal(f)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp := path + ".tmp"
	w, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	if _, err := w.Write(raw); err != nil {
		_ = w.Close()
		return err
	}
	if err := w.Sync(); err != nil {
		_ = w.Close()
		return err
	}
	if err := w.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
