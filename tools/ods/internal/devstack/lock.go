package devstack

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// lockOwner is written into the lock file so a blocked caller can say who
// holds it.
type lockOwner struct {
	PID       int       `json:"pid"`
	Command   string    `json:"command"`
	StartedAt time.Time `json:"started_at"`
}

// ErrLocked is returned when the lifecycle lock could not be taken in time.
var ErrLocked = errors.New("dev stack is locked by another process")

// Lock takes the worktree's exclusive lifecycle lock, waiting up to wait for
// another holder to finish. It returns the release function.
func (s *Stack) Lock(ctx context.Context, command string, wait time.Duration) (func(), error) {
	if err := os.MkdirAll(s.StateDir, 0o755); err != nil {
		return nil, err
	}
	path := filepath.Join(s.StateDir, lockFileName)
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return nil, err
	}

	deadline := time.Now().Add(wait)
	for {
		err := tryFlock(f)
		if err == nil {
			break
		}
		if !errors.Is(err, errWouldBlock) {
			_ = f.Close()
			return nil, err
		}
		if time.Now().After(deadline) {
			owner := readLockOwner(path)
			_ = f.Close()
			return nil, fmt.Errorf("%w: %s", ErrLocked, owner)
		}
		select {
		case <-ctx.Done():
			_ = f.Close()
			return nil, ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}

	owner, _ := json.Marshal(lockOwner{PID: os.Getpid(), Command: command, StartedAt: time.Now().UTC()})
	_ = f.Truncate(0)
	_, _ = f.WriteAt(owner, 0)

	return func() {
		_ = f.Truncate(0)
		_ = unflock(f)
		_ = f.Close()
	}, nil
}

func readLockOwner(path string) string {
	data, err := os.ReadFile(path)
	if err != nil || len(data) == 0 {
		return "unknown owner"
	}
	var owner lockOwner
	if err := json.Unmarshal(data, &owner); err != nil {
		return "unknown owner"
	}
	return fmt.Sprintf("%s (pid %d, since %s)", owner.Command, owner.PID, owner.StartedAt.Format(time.RFC3339))
}
