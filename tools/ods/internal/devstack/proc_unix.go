//go:build !windows

package devstack

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	log "github.com/sirupsen/logrus"
	"golang.org/x/sys/unix"
)

// startService launches sp in its own process group with its output in
// logPath, and returns the record that identifies the process.
func startService(sp Spec, logPath string) (ServiceRecord, error) {
	record, _, err := launchProcess(sp, logPath, ServiceIO{}, false)
	return record, err
}

func launchService(sp Spec, logPath string, streams ServiceIO) (ServiceRecord, <-chan error, error) {
	return launchProcess(sp, logPath, streams, true)
}

type serviceOutputCopy struct {
	reader *os.File
	writer *os.File
	output io.Writer
	done   chan error
}

func launchProcess(sp Spec, logPath string, streams ServiceIO, foreground bool) (ServiceRecord, <-chan error, error) {
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		return ServiceRecord{}, nil, err
	}
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return ServiceRecord{}, nil, err
	}
	if _, err := fmt.Fprintf(logFile, "cwd: %s\ncommand: %s\n\n", sp.Dir, strings.Join(sp.Command, " ")); err != nil {
		_ = logFile.Close()
		return ServiceRecord{}, nil, err
	}

	startedAt := time.Now().UTC().Truncate(time.Second)
	cmd := exec.Command(sp.Command[0], sp.Command[1:]...)
	cmd.Dir = sp.Dir
	cmd.Env = sp.Env
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	var copies []serviceOutputCopy
	defer func() {
		for _, copy := range copies {
			_ = copy.writer.Close()
		}
	}()
	if streams.Stdout != nil {
		reader, writer, err := os.Pipe()
		if err != nil {
			_ = logFile.Close()
			return ServiceRecord{}, nil, err
		}
		copies = append(copies, serviceOutputCopy{reader, writer, io.MultiWriter(logFile, streams.Stdout), make(chan error, 1)})
		cmd.Stdout = writer
	}
	if streams.Stderr != nil {
		reader, writer, err := os.Pipe()
		if err != nil {
			for _, copy := range copies {
				_ = copy.reader.Close()
			}
			_ = logFile.Close()
			return ServiceRecord{}, nil, err
		}
		copies = append(copies, serviceOutputCopy{reader, writer, io.MultiWriter(logFile, streams.Stderr), make(chan error, 1)})
		cmd.Stderr = writer
	}
	cmd.Stdin = streams.Stdin
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	terminalInput := -1
	var inputReader, inputWriter *os.File
	if input, ok := streams.Stdin.(*os.File); ok && input == os.Stdin {
		fd := int(input.Fd())
		foreground, err := unix.IoctlGetInt(fd, unix.TIOCGPGRP)
		if err == nil && foreground == syscall.Getpgrp() {
			// Keep terminal signals on ODS so it can enforce the stop deadline.
			terminalInput, err = unix.Open("/dev/tty", unix.O_RDONLY|unix.O_NONBLOCK|unix.O_CLOEXEC, 0)
			if err == nil {
				inputReader, inputWriter, err = os.Pipe()
			}
			if err != nil {
				if terminalInput >= 0 {
					_ = unix.Close(terminalInput)
				}
				for _, copy := range copies {
					_ = copy.reader.Close()
				}
				_ = logFile.Close()
				return ServiceRecord{}, nil, err
			}
			cmd.Stdin = inputReader
		}
	}
	if err := cmd.Start(); err != nil {
		if inputReader != nil {
			_ = inputReader.Close()
			_ = inputWriter.Close()
			_ = unix.Close(terminalInput)
		}
		for _, copy := range copies {
			_ = copy.reader.Close()
		}
		_ = logFile.Close()
		return ServiceRecord{}, nil, fmt.Errorf("start %s: %w", sp.Name, err)
	}
	stopInput := func() {}
	if terminalInput >= 0 {
		_ = inputReader.Close()
		stop := make(chan struct{})
		inputDone := make(chan struct{})
		go func() {
			defer close(inputDone)
			defer func() { _ = inputWriter.Close() }()
			defer func() { _ = unix.Close(terminalInput) }()
			// macOS cannot poll /dev/tty; poll stdin and read without blocking.
			poll := []unix.PollFd{{Fd: int32(os.Stdin.Fd()), Events: unix.POLLIN}}
			buffer := make([]byte, 4096)
			for {
				select {
				case <-stop:
					return
				default:
				}
				_, err := unix.Poll(poll, 100)
				if errors.Is(err, unix.EINTR) {
					continue
				}
				if err != nil || poll[0].Revents&(unix.POLLERR|unix.POLLNVAL) != 0 {
					return
				}
				if poll[0].Revents&(unix.POLLIN|unix.POLLHUP) == 0 {
					continue
				}
				n, err := unix.Read(terminalInput, buffer)
				if errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN) {
					continue
				}
				if err != nil || n == 0 {
					return
				}
				if _, err := inputWriter.Write(buffer[:n]); err != nil {
					return
				}
			}
		}()
		stopInput = func() {
			close(stop)
			_ = inputWriter.Close()
			<-inputDone
		}
	}
	pid := cmd.Process.Pid
	record := ServiceRecord{
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
	}
	for _, copy := range copies {
		go func() {
			_, err := io.Copy(copy.output, copy.reader)
			_ = copy.reader.Close()
			copy.done <- err
		}()
	}
	if foreground {
		rememberGroupMembers(&record)
	}
	supervised := record
	supervised.Members = make(map[int]string, len(record.Members))
	for pid, marker := range record.Members {
		supervised.Members[pid] = marker
	}
	done := make(chan error, 1)
	go func() {
		var err error
		if foreground {
			err = waitForegroundProcess(cmd, supervised, copies)
		} else {
			err = cmd.Wait()
		}
		stopInput()
		_ = logFile.Close()
		done <- err
		close(done)
	}()
	return record, done, nil
}

func waitForegroundProcess(cmd *exec.Cmd, record ServiceRecord, copies []serviceOutputCopy) error {
	for pidAlive(record.PID) {
		time.Sleep(100 * time.Millisecond)
	}
	// Our unreaped child reserves its PID and PGID until this final capture.
	rememberGroupMembers(&record)
	err := cmd.Wait()
	if left := stopRecordsWithKillWait([]ServiceRecord{record}, 250*time.Millisecond, time.Second); len(left) > 0 {
		err = errors.Join(err, &serviceCleanupError{record: record})
	}
	deadline := time.NewTimer(time.Second)
	defer deadline.Stop()
	for _, copy := range copies {
		select {
		case copyErr := <-copy.done:
			err = errors.Join(err, copyErr)
		case <-deadline.C:
			for _, pending := range copies {
				_ = pending.reader.Close()
			}
			return errors.Join(err, fmt.Errorf("service output did not drain before timeout"))
		}
	}
	return err
}

func signalService(rec ServiceRecord, signal os.Signal) error {
	if !groupIsOurs(rec) {
		return nil
	}
	err := syscall.Kill(-rec.PGID, signal.(syscall.Signal))
	if errors.Is(err, syscall.ESRCH) {
		return nil
	}
	return err
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
	rememberGroupMembers(rec)
}

func rememberGroupMembers(rec *ServiceRecord) {
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
	postKill := 5 * time.Second
	if timeout == 0 {
		postKill = 0
	}
	return stopRecordsWithKillWait(recs, timeout, postKill)
}

func stopRecordsWithKillWait(recs []ServiceRecord, timeout, postKill time.Duration) []ServiceRecord {
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
	return append(waitGroups(killed, postKill), unresolved...)
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

// portHeldByGroup reports whether a process in the group listens on port.
// Without lsof it falls back to the port being bound at all.
func portHeldByGroup(port, pgid int) bool {
	out, err := exec.Command("lsof", "-t", "-nP", "-iTCP:"+strconv.Itoa(port), "-sTCP:LISTEN").Output()
	if err != nil {
		if _, lookErr := exec.LookPath("lsof"); lookErr != nil {
			return !bindable(port)
		}
		return false
	}
	members := map[int]bool{}
	for _, pid := range groupMembers(pgid) {
		members[pid] = true
	}
	for _, field := range strings.Fields(string(out)) {
		if pid, err := strconv.Atoi(field); err == nil && members[pid] {
			return true
		}
	}
	return false
}
