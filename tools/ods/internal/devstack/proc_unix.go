//go:build !windows

package devstack

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	log "github.com/sirupsen/logrus"
)

// startService launches sp in its own process group with its output in
// logPath, and returns the record that identifies the process.
func startService(sp Spec, logPath string) (ServiceRecord, error) {
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		return ServiceRecord{}, err
	}
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return ServiceRecord{}, err
	}
	defer func() { _ = logFile.Close() }()
	if _, err := fmt.Fprintf(logFile, "cwd: %s\ncommand: %s\n\n", sp.Dir, strings.Join(sp.Command, " ")); err != nil {
		return ServiceRecord{}, err
	}

	startedAt := time.Now().UTC().Truncate(time.Second)
	cmd := exec.Command(sp.Command[0], sp.Command[1:]...)
	cmd.Dir = sp.Dir
	cmd.Env = sp.Env
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Stdin = nil
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		return ServiceRecord{}, fmt.Errorf("start %s: %w", sp.Name, err)
	}
	pid := cmd.Process.Pid
	// Reap the child if it exits while this process is still around, so it
	// never lingers as a zombie that looks alive. When ods exits first, init
	// reaps it.
	go func() { _ = cmd.Wait() }()
	return ServiceRecord{
		Name:        sp.Name,
		Slug:        sp.Slug,
		Command:     sp.Command,
		Dir:         sp.Dir,
		SpecHash:    sp.Hash(),
		Port:        sp.Port,
		Health:      sp.Health,
		Optional:    sp.Optional,
		PID:         pid,
		PGID:        pid,
		StartMarker: startMarker(pid),
		StartedAt:   startedAt,
		Log:         logPath,
	}, nil
}

// isCurrent reports whether the recorded leader process is still the one
// that was started: alive, in its own group, with the same start time.
func isCurrent(rec ServiceRecord) bool {
	if rec.PID <= 0 || !pidAlive(rec.PID) {
		return false
	}
	pgid, err := syscall.Getpgid(rec.PID)
	if err != nil || pgid != rec.PGID {
		return false
	}
	return rec.StartMarker != "" && startMarker(rec.PID) == rec.StartMarker
}

// pidAlive reports whether pid exists and is not a zombie.
func pidAlive(pid int) bool {
	err := syscall.Kill(pid, 0)
	if err != nil && !errors.Is(err, syscall.EPERM) {
		return false
	}
	out, err := exec.Command("ps", "-p", strconv.Itoa(pid), "-o", "stat=").Output()
	if err != nil {
		return false
	}
	return !strings.HasPrefix(strings.TrimSpace(string(out)), "Z")
}

// groupAlive reports whether any live process is left in the group.
func groupAlive(pgid int) bool {
	if pgid <= 1 {
		return false
	}
	err := syscall.Kill(-pgid, 0)
	if err != nil && !errors.Is(err, syscall.EPERM) {
		return false
	}
	return len(groupMembers(pgid)) > 0
}

// startMarker returns the process start time as ps prints it, which with the
// pid identifies one process incarnation.
func startMarker(pid int) string {
	out, err := exec.Command("ps", "-p", strconv.Itoa(pid), "-o", "lstart=").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// groupIsOurs decides whether signalling the group is safe. The leader
// proves it while alive. After the leader exits, the group is still ours
// while a member we recorded (pid and start time) is still running: a
// process group id cannot be reused until the group is empty.
func groupIsOurs(rec ServiceRecord) bool {
	if isCurrent(rec) {
		return true
	}
	if pidAlive(rec.PID) {
		return false
	}
	members := groupMembers(rec.PGID)
	for _, pid := range members {
		if marker := rec.Members[pid]; marker != "" && marker == startMarker(pid) {
			return true
		}
	}
	return false
}

func rememberGroup(rec *ServiceRecord) {
	if !isCurrent(*rec) {
		return
	}
	if rec.Members == nil {
		rec.Members = map[int]string{}
	}
	for _, pid := range groupMembers(rec.PGID) {
		if marker := startMarker(pid); marker != "" {
			rec.Members[pid] = marker
		}
	}
}

// groupMembers lists the live (non-zombie) pids in a process group.
func groupMembers(pgid int) []int {
	out, err := exec.Command("ps", "-A", "-o", "pid=", "-o", "pgid=", "-o", "stat=").Output()
	if err != nil {
		return nil
	}
	var pids []int
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 3 || strings.HasPrefix(fields[2], "Z") {
			continue
		}
		pid, err1 := strconv.Atoi(fields[0])
		gid, err2 := strconv.Atoi(fields[1])
		if err1 == nil && err2 == nil && gid == pgid {
			pids = append(pids, pid)
		}
	}
	return pids
}

// stopRecords terminates the groups of recs that are still ours and waits
// for every member to exit, escalating to SIGKILL after timeout. It returns
// the records that still have members alive.
func stopRecords(recs []ServiceRecord, timeout time.Duration) []ServiceRecord {
	var active []ServiceRecord
	var unresolved []ServiceRecord
	for _, rec := range recs {
		rememberGroup(&rec)
		if rec.PGID <= 1 || !groupIsOurs(rec) {
			if rec.PGID > 1 && !pidAlive(rec.PID) && groupAlive(rec.PGID) {
				log.Warnf("Cannot prove ownership of surviving process group %d for %s", rec.PGID, rec.Name)
				unresolved = append(unresolved, rec)
			}
			continue
		}
		log.Debugf("Stopping %s (pgid %d)", rec.Name, rec.PGID)
		_ = syscall.Kill(-rec.PGID, syscall.SIGTERM)
		active = append(active, rec)
	}
	var killed []ServiceRecord
	for _, rec := range waitGroups(active, timeout) {
		if !groupIsOurs(rec) {
			// Still alive, but no recorded member proves the group is ours
			// any more: report it rather than kill or forget it.
			log.Warnf("Cannot prove ownership of surviving process group %d for %s", rec.PGID, rec.Name)
			unresolved = append(unresolved, rec)
			continue
		}
		log.Warnf("%s did not stop in %s, killing its process group", rec.Name, timeout)
		_ = syscall.Kill(-rec.PGID, syscall.SIGKILL)
		killed = append(killed, rec)
	}
	return append(waitGroups(killed, 5*time.Second), unresolved...)
}

func waitGroups(recs []ServiceRecord, timeout time.Duration) []ServiceRecord {
	deadline := time.Now().Add(timeout)
	for len(recs) > 0 {
		// A group stays tracked while any member lives, whether or not
		// ownership can still be proven.
		var left []ServiceRecord
		for _, rec := range recs {
			if groupAlive(rec.PGID) {
				left = append(left, rec)
			}
		}
		recs = left
		if len(recs) == 0 || time.Now().After(deadline) {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	return recs
}
