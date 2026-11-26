package browser

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"os"
	"os/exec"
	"strconv"
	"syscall"
	"time"
)

// ensureService starts the service if it is configured and its socket does
// not accept connections, and waits until the socket accepts them.
func (b *Browser) ensureService(ctx context.Context, r *running, env []string) error {
	if b.cfg.ServiceScript == "" {
		return nil
	}
	if r.svc != nil && !r.svc.exited() {
		// A command can remove the socket, and the listener can die while
		// the process runs on.
		if c, err := b.DialService(ctx); err == nil {
			_ = c.Close()
			return nil
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := b.stopService(r); err != nil {
		b.cfg.Log.Warn("stop the old browser service", "err", err)
	}
	s, err := b.launchService(r, env)
	if err != nil {
		return fmt.Errorf("start the browser service: %w", err)
	}
	r.svc = s
	accepts := func(ctx context.Context) bool {
		c, err := b.DialService(ctx)
		if err == nil {
			_ = c.Close()
		}
		return err == nil
	}
	if err := b.waitUntil(ctx, s.done, "the browser service", accepts); err != nil {
		return withStderr(errors.Join(err, b.stopService(r)), "browser service", s.stderr)
	}
	b.cfg.Log.Info("browser service started", "pid", s.pid, "socket", b.SocketPath())
	return nil
}

func (b *Browser) launchService(r *running, env []string) (*proc, error) {
	if err := b.prepareSocketDir(); err != nil {
		return nil, err
	}
	env = append(append([]string{}, env...),
		"ONYX_BROWSER_CDP_URL=http://127.0.0.1:"+strconv.Itoa(r.port),
		"ONYX_BROWSER_SOCKET="+b.SocketPath(),
		"ONYX_SESSIONS_ROOT="+b.cfg.SessionsRoot,
	)
	cmd := &exec.Cmd{Path: b.cfg.Node, Args: []string{b.cfg.Node, b.cfg.ServiceScript}, Env: env}
	// Chrome's cgroup: a kill of the cgroup also ends the service.
	return b.startProc(r.group, cmd)
}

// prepareSocketDir makes the socket dir, owned by the command user, and
// removes a stale socket.
func (b *Browser) prepareSocketDir() error {
	dir := b.cfg.SocketDir
	if err := os.Mkdir(dir, 0o700); err != nil && !errors.Is(err, fs.ErrExist) {
		return err
	}
	if c := b.cfg.Credential; c != nil {
		if err := os.Lchown(dir, int(c.Uid), int(c.Gid)); err != nil {
			return err
		}
	}
	if err := os.Remove(b.SocketPath()); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	return nil
}

// stopService kills the service's process group.
func (b *Browser) stopService(r *running) error {
	s := r.svc
	if s == nil {
		return nil
	}
	r.svc = nil
	if s.exited() {
		// Its PID may now lead another process group. Chrome's group kill
		// ends anything that it left.
		return nil
	}
	var err error
	if kerr := syscall.Kill(-s.pid, syscall.SIGKILL); kerr != nil && !errors.Is(kerr, syscall.ESRCH) {
		err = kerr
	}
	select {
	case <-s.done:
	case <-time.After(stopTimeout):
		err = errors.Join(err, fmt.Errorf("browser service pid %d did not exit in %v", s.pid, stopTimeout))
	}
	return err
}

// DialService connects to the service socket. It fails when no service
// listens.
func (b *Browser) DialService(ctx context.Context) (net.Conn, error) {
	var d net.Dialer
	return d.DialContext(ctx, "unix", b.SocketPath())
}
