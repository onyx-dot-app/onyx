//go:build kvm && linux

package kvmtest

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// countSleeps counts the test's "sleep 4242" processes in the guest.
const countSleeps = `n=0; for f in /proc/[0-9]*/cmdline; do [ "$(tr '\0' ' ' <$f 2>/dev/null)" = "sleep 4242 " ] && n=$((n+1)); done; echo $n`

// TestDaemonKVM boots KVM_VMS VMs, runs Init → Run(echo) in each, and checks
// cancel, deadline, disconnect and daemon restart on the first VM.
func TestDaemonKVM(t *testing.T) {
	e := loadEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()

	vms := make([]*vm, e.VMs)
	bootStart := time.Now()
	for i := range vms {
		vms[i] = bootVM(t, e, fmt.Sprintf("vm-%02d", i), "")
	}
	ready := make([]time.Duration, e.VMs)
	errs := make([]error, e.VMs)
	var wg sync.WaitGroup
	for i, v := range vms {
		wg.Go(func() {
			_, errs[i] = waitHealth(ctx, v)
			ready[i] = time.Since(bootStart)
		})
	}
	wg.Wait()
	var readyMS []float64
	for i, err := range errs {
		if err != nil {
			t.Fatalf("vm %d: %v\nconsole: %s", i, err, vms[i].console())
		}
		readyMS = append(readyMS, ms(ready[i]))
	}
	t.Logf("BENCH boot_to_health_ms n=%d p50=%.0f p95=%.0f max=%.0f (all %d started at once)",
		e.VMs, pct(readyMS, 0.5), pct(readyMS, 0.95), pct(readyMS, 1), e.VMs)

	// Init → Run(echo) in each VM, one VM at a time.
	var initMS, runMS, totalMS, offBefore, offAfter []float64
	keys := make([]string, e.VMs)
	for i, v := range vms {
		c, conn := client(t, v)
		h, err := c.Health(ctx, &pb.HealthRequest{})
		if err != nil {
			t.Fatal(err)
		}
		offBefore = append(offBefore, ms(time.Until(h.GetGuestTime().AsTime())))
		keys[i] = randHex(32)
		sid := fmt.Sprintf("sandbox-%02d", i)

		t0 := time.Now()
		ir, err := keyInit(ctx, c, keys[i], initRequest(sid))
		if err != nil {
			t.Fatalf("vm %d init: %v\nconsole: %s", i, err, v.console())
		}
		t1 := time.Now()
		r, err := run(keyed(ctx, keys[i]), c, &pb.Command{Argv: []string{"echo", "hello"}})
		t2 := time.Now()
		if err != nil || r.stdout != "hello\n" || r.res.GetCompletion() != pb.Completion_EXITED || r.res.GetExitCode() != 0 {
			t.Fatalf("vm %d run: %v %q %v", i, err, r.stdout, r.res)
		}
		initMS, runMS, totalMS = append(initMS, ms(t1.Sub(t0))), append(runMS, ms(t2.Sub(t1))), append(totalMS, ms(t2.Sub(t0)))
		if i == 0 {
			t.Logf("vm 0 init: clock_step=%v entropy_credited=%v attached=%v relay_reset=%v grown=%v", ir.GetClockStep().AsDuration(),
				ir.GetEntropyCredited(), ir.GetAttached(), ir.GetRelayReset(), ir.GetGrown())
			if len(ir.GetGrown()) != 1 || ir.GetGrown()[0].GetNewBytes() <= ir.GetGrown()[0].GetOldBytes() {
				t.Errorf("scratch did not grow: %v", ir.GetGrown())
			}
			if !ir.GetEntropyCredited() {
				t.Errorf("entropy not credited")
			}
			// The cold boot ran attach already; Init runs it again (a no-op)
			// and signals the relay that init started.
			if !ir.GetAttached() || !ir.GetRelayReset() {
				t.Errorf("init: attached=%v relay_reset=%v, want both true", ir.GetAttached(), ir.GetRelayReset())
			}
		}
		s := time.Now()
		h, err = c.Health(ctx, &pb.HealthRequest{})
		if err != nil || !h.GetInitialized() || h.GetSandboxId() != sid {
			t.Fatalf("vm %d health after init: %v %v", i, h, err)
		}
		rtt := time.Since(s)
		offAfter = append(offAfter, ms(h.GetGuestTime().AsTime().Sub(s.Add(rtt/2))))
		_ = conn.Close()
	}
	t.Logf("BENCH init_ms p50=%.2f p95=%.2f max=%.2f", pct(initMS, 0.5), pct(initMS, 0.95), pct(initMS, 1))
	t.Logf("BENCH run_echo_ms p50=%.2f p95=%.2f max=%.2f", pct(runMS, 0.5), pct(runMS, 0.95), pct(runMS, 1))
	t.Logf("BENCH init_plus_run_ms n=%d p50=%.2f p95=%.2f max=%.2f", len(totalMS), pct(totalMS, 0.5), pct(totalMS, 0.95), pct(totalMS, 1))
	t.Logf("BENCH clock_offset_before_init_ms p50=%.1f min=%.1f max=%.1f", pct(offBefore, 0.5), pct(offBefore, 0), pct(offBefore, 1))
	t.Logf("BENCH clock_offset_after_init_ms p50=%.2f min=%.2f max=%.2f", pct(offAfter, 0.5), pct(offAfter, 0), pct(offAfter, 1))

	v, key := vms[0], keys[0]
	c, _ := client(t, v)
	kctx := keyed(ctx, key)

	t.Run("cgroup", func(t *testing.T) {
		r, err := run(kctx, c, sh("cat /proc/self/cgroup"))
		if err != nil || !strings.HasPrefix(strings.TrimSpace(r.stdout), "0::/guestd/"+r.id) {
			t.Fatalf("cgroup: %q (id %s) %v", r.stdout, r.id, err)
		}
		t.Logf("command cgroup: %s", strings.TrimSpace(r.stdout))
	})

	t.Run("cancel", func(t *testing.T) {
		st, err := c.Start(kctx, &pb.StartRequest{Command: sh(`sleep 4242 & sleep 4242 & setsid sleep 4242 & echo up; wait`)})
		if err != nil {
			t.Fatal(err)
		}
		id := st.GetStarted().GetExecutionId()
		waitOutput(kctx, t, c, id, "up")
		if r, _ := run(kctx, c, sh(countSleeps)); strings.TrimSpace(r.stdout) != "3" {
			t.Fatalf("sleeps before cancel: %q", r.stdout)
		}
		s := time.Now()
		cr, err := c.Cancel(kctx, &pb.CancelRequest{ExecutionId: id})
		took := time.Since(s)
		if err != nil || cr.GetResult().GetCompletion() != pb.Completion_CANCELED {
			t.Fatalf("cancel: %v %v", cr, err)
		}
		r, _ := run(kctx, c, sh(countSleeps))
		if strings.TrimSpace(r.stdout) != "0" {
			t.Fatalf("sleeps after cancel: %q", r.stdout)
		}
		t.Logf("BENCH cancel_sleep_tree_ms=%.2f (3 sleeps, one after setsid; 0 left)", ms(took))
	})

	t.Run("deadline", func(t *testing.T) {
		cmd := sh(`sleep 4242 & setsid sleep 4242 & wait`)
		cmd.Deadline = durationpb.New(2 * time.Second)
		s := time.Now()
		r, err := run(kctx, c, cmd)
		took := time.Since(s)
		if err != nil || r.res.GetCompletion() != pb.Completion_DEADLINE_EXCEEDED {
			t.Fatalf("deadline: %v %v", r.res, err)
		}
		left, _ := run(kctx, c, sh(countSleeps))
		if strings.TrimSpace(left.stdout) != "0" {
			t.Fatalf("sleeps after deadline: %q", left.stdout)
		}
		t.Logf("BENCH deadline_2s_result_ms=%.0f (0 sleeps left)", ms(took))
	})

	t.Run("disconnect", func(t *testing.T) {
		c1, conn1 := client(t, v)
		s, err := c1.Run(kctx, &pb.RunRequest{Command: sh(`for i in 1 2 3 4 5; do echo $i; sleep 1; done; exit 7`)})
		if err != nil {
			t.Fatal(err)
		}
		ev, err := s.Recv()
		if err != nil {
			t.Fatal(err)
		}
		id := ev.GetStarted().GetExecutionId()
		_ = conn1.Close()

		c2, _ := client(t, v)
		ins, err := c2.Inspect(kctx, &pb.InspectRequest{ExecutionId: id})
		if err != nil || ins.GetExecution().GetState() != pb.ExecState_RUNNING {
			t.Fatalf("inspect after drop: %v %v", ins, err)
		}
		st, err := c2.Stream(kctx, &pb.StreamRequest{ExecutionId: id})
		if err != nil {
			t.Fatal(err)
		}
		r, err := collect(st)
		if err != nil || r.stdout != "1\n2\n3\n4\n5\n" || r.res.GetCompletion() != pb.Completion_EXITED || r.res.GetExitCode() != 7 {
			t.Fatalf("stream after reconnect: %q %v %v", r.stdout, r.res, err)
		}
	})

	t.Run("interact", func(t *testing.T) {
		st, err := c.Start(kctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"sh", "-c", "read a; echo got:$a"}, Stdin: true}})
		if err != nil {
			t.Fatal(err)
		}
		id := st.GetStarted().GetExecutionId()
		if _, err := c.Interact(kctx, &pb.InteractRequest{ExecutionId: id, Data: []byte("vsock\n"), CloseStdin: true}); err != nil {
			t.Fatal(err)
		}
		s, _ := c.Stream(kctx, &pb.StreamRequest{ExecutionId: id})
		if r, err := collect(s); err != nil || r.stdout != "got:vsock\n" {
			t.Fatalf("interact: %q %v", r.stdout, err)
		}
	})

	t.Run("egress-relay", func(t *testing.T) {
		bin := os.Getenv("KVM_RELAY_BIN")
		if bin == "" {
			t.Skip("KVM_RELAY_BIN not set")
		}
		testEgressRelay(kctx, t, v, c, bin)
	})

	t.Run("daemon-restart", func(t *testing.T) {
		// The init restarts the daemon; the Init state and key survive.
		kill := `for p in /proc/[0-9]*; do case "$(readlink $p/exe)" in *guest-daemon*) kill -9 ${p#/proc/};; esac; done`
		_, _ = c.Start(kctx, &pb.StartRequest{Command: sh(kill)})
		s := time.Now()
		var h *pb.HealthResponse
		for {
			var err error
			h, err = waitHealth(ctx, v)
			if err != nil {
				t.Fatal(err)
			}
			if h.GetUptime().AsDuration() < time.Since(s)+time.Second {
				break
			}
		}
		if !h.GetInitialized() {
			t.Fatalf("health after restart: %v", h)
		}
		c3, _ := client(t, v)
		if r, err := run(kctx, c3, &pb.Command{Argv: []string{"true"}}); err != nil || r.res.GetExitCode() != 0 {
			t.Fatalf("run after restart: %v %v", r.res, err)
		}
		if _, err := run(ctx, c3, &pb.Command{Argv: []string{"true"}}); err == nil {
			t.Fatal("run without key after restart succeeded")
		}
		t.Logf("BENCH daemon_restart_to_health_ms=%.0f", ms(time.Since(s)))
	})
}

// waitOutput streams an execution until its stdout contains want.
func waitOutput(kctx context.Context, t *testing.T, c pb.SandboxdClient, id, want string) {
	t.Helper()
	sctx, cancel := context.WithTimeout(kctx, 10*time.Second)
	defer cancel()
	s, err := c.Stream(sctx, &pb.StreamRequest{ExecutionId: id})
	if err != nil {
		t.Fatal(err)
	}
	var out strings.Builder
	for !strings.Contains(out.String(), want) {
		ev, err := s.Recv()
		if err != nil {
			t.Fatalf("waiting for %q: %v (got %q)", want, err, out.String())
		}
		out.Write(ev.GetOutput().GetData())
	}
}

// TestRestoreKVM snapshots a VM before Init, waits KVM_RESTORE_GAP, and
// restores two clones: Init fixes the clock, and the clones get different
// randomness and execution IDs.
func TestRestoreKVM(t *testing.T) {
	e := loadEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	tpl := bootVM(t, e, "tpl", e.TemplateArgs)
	if _, err := waitHealth(ctx, tpl); err != nil {
		t.Fatalf("%v\nconsole: %s", err, tpl.console())
	}
	if err := fcAPI(ctx, tpl.dir, http.MethodPatch, "/vm", map[string]string{"state": "Paused"}); err != nil {
		t.Fatal(err)
	}
	if err := fcAPI(ctx, tpl.dir, http.MethodPut, "/snapshot/create", map[string]string{
		"snapshot_type": "Full", "snapshot_path": "vmstate", "mem_file_path": "mem",
	}); err != nil {
		t.Fatal(err)
	}
	tpl.kill()
	snapAt := time.Now()
	t.Logf("snapshot taken; waiting %v", e.RestoreGap)
	time.Sleep(e.RestoreGap)

	type clone struct {
		v   *vm
		key string
	}
	var clones []clone
	for i := range 2 {
		dir := prepareDir(t, e, fmt.Sprintf("clone-%d", i))
		for _, f := range []string{"vmstate", "mem"} {
			if err := os.Link(filepath.Join(tpl.dir, f), filepath.Join(dir, f)); err != nil {
				t.Fatal(err)
			}
		}
		// Each clone has its own new scratch disk; Init attaches and grows it.
		v := startFC(t, e, dir)
		if err := waitAPI(ctx, dir); err != nil {
			t.Fatal(err)
		}
		s := time.Now()
		if err := fcAPI(ctx, dir, http.MethodPut, "/snapshot/load", map[string]any{
			"snapshot_path": "vmstate", "mem_backend": map[string]string{"backend_type": "File", "backend_path": "mem"}, "resume_vm": true,
		}); err != nil {
			t.Fatalf("load: %v\nconsole: %s", err, v.console())
		}
		h, err := waitHealth(ctx, v)
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("BENCH clone %d restore_to_health_ms=%.1f", i, ms(time.Since(s)))
		off := time.Until(h.GetGuestTime().AsTime())
		t.Logf("clone %d before Init: guest clock offset %v (snapshot %v ago), initialized=%v", i, off.Round(time.Millisecond), time.Since(snapAt).Round(time.Second), h.GetInitialized())
		if off > -e.RestoreGap/2 {
			t.Errorf("clone %d: expected the guest clock to lag by about the gap, got %v", i, off)
		}
		if h.GetInitialized() {
			t.Errorf("clone %d: template must not be initialized", i)
		}

		c, _ := client(t, v)
		key := randHex(32)
		req := initRequest(fmt.Sprintf("clone-%d", i))
		s = time.Now()
		req.HostTime = timestamppb.New(s)
		ir, err := keyInit(ctx, c, key, req)
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("BENCH clone %d init_ms=%.2f clock_step=%v attached=%v relay_reset=%v grown=%v", i, ms(time.Since(s)),
			ir.GetClockStep().AsDuration().Round(time.Millisecond), ir.GetAttached(), ir.GetRelayReset(), ir.GetGrown())
		if len(ir.GetGrown()) != 1 || ir.GetGrown()[0].GetNewBytes() <= ir.GetGrown()[0].GetOldBytes() {
			t.Errorf("clone %d: scratch not attached and grown: %v", i, ir.GetGrown())
		}
		if !ir.GetAttached() || !ir.GetRelayReset() {
			t.Errorf("clone %d init: attached=%v relay_reset=%v, want both true", i, ir.GetAttached(), ir.GetRelayReset())
		}
		if r, err := run(keyed(ctx, key), c, sh("grep -c ' overlay ' /proc/mounts; grep ' /workspace/managed ' /proc/mounts | cut -d' ' -f4 | cut -c1-2")); err == nil {
			t.Logf("clone %d after Init: overlay mounts / managed mount: %q", i, r.stdout)
		}
		s = time.Now()
		h, _ = c.Health(ctx, &pb.HealthRequest{})
		rtt := time.Since(s)
		after := h.GetGuestTime().AsTime().Sub(s.Add(rtt / 2))
		t.Logf("BENCH clone %d clock_offset_after_init_ms=%.2f", i, ms(after))
		if after > 50*time.Millisecond || after < -50*time.Millisecond {
			t.Errorf("clone %d: clock offset after Init %v", i, after)
		}
		clones = append(clones, clone{v: v, key: key})
	}

	var rnd, ids []string
	for _, cl := range clones {
		c, _ := client(t, cl.v)
		r, err := run(keyed(ctx, cl.key), c, sh("head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \\n'"))
		if err != nil {
			t.Fatal(err)
		}
		rnd, ids = append(rnd, r.stdout), append(ids, r.id)
	}
	t.Logf("urandom: %v; execution IDs: %v", rnd, ids)
	if rnd[0] == rnd[1] || ids[0] == ids[1] {
		t.Fatalf("clones share state: urandom %v ids %v", rnd, ids)
	}
}

// testEgressRelay copies the egress-relay binary into the VM through
// Interact, runs it on 127.0.0.1:13128 and checks a guest client against a
// host echo server on the VM's vsock port 3128, then SIGHUP.
func testEgressRelay(kctx context.Context, t *testing.T, v *vm, c pb.SandboxdClient, bin string) {
	t.Helper()
	ln, err := net.Listen("unix", v.vsock()+"_3128")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	upEnded := make(chan struct{}, 16)
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				_, _ = io.Copy(conn, conn)
				_ = conn.Close()
				upEnded <- struct{}{}
			}()
		}
	}()

	raw, err := os.ReadFile(bin)
	if err != nil {
		t.Fatal(err)
	}
	st, err := c.Start(kctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"sh", "-c", "cat > /tmp/egress-relay && chmod 755 /tmp/egress-relay"}, Stdin: true}})
	if err != nil {
		t.Fatal(err)
	}
	up := time.Now()
	for off := 0; off < len(raw); off += 1 << 20 {
		end := min(off+1<<20, len(raw))
		if _, err := c.Interact(kctx, &pb.InteractRequest{ExecutionId: st.GetStarted().GetExecutionId(), Data: raw[off:end], CloseStdin: end == len(raw)}); err != nil {
			t.Fatal(err)
		}
	}
	s, _ := c.Stream(kctx, &pb.StreamRequest{ExecutionId: st.GetStarted().GetExecutionId()})
	if r, err := collect(s); err != nil || r.res.GetExitCode() != 0 {
		t.Fatalf("copy relay: %v %v", r.res, err)
	}
	t.Logf("BENCH interact_upload_mib_s=%.1f (%d bytes)", float64(len(raw))/(1<<20)/time.Since(up).Seconds(), len(raw))

	cmd := &pb.Command{Argv: []string{"/tmp/egress-relay", "--listen", "127.0.0.1:13128"}, Deadline: durationpb.New(5 * time.Minute)}
	rs, err := c.Start(kctx, &pb.StartRequest{Command: cmd})
	if err != nil {
		t.Fatal(err)
	}
	relayID, relayPID := rs.GetStarted().GetExecutionId(), rs.GetStarted().GetPid()
	defer func() { _, _ = c.Cancel(kctx, &pb.CancelRequest{ExecutionId: relayID}) }()
	// relayLog stops the relay and returns its log, or why it has none.
	relayLog := func() string {
		lctx, cancel := context.WithTimeout(kctx, 10*time.Second)
		defer cancel()
		_, _ = c.Cancel(lctx, &pb.CancelRequest{ExecutionId: relayID})
		s, err := c.Stream(lctx, &pb.StreamRequest{ExecutionId: relayID})
		if err != nil {
			return fmt.Sprintf("(no relay log: %v)", err)
		}
		lr, err := collect(s)
		if err != nil {
			return fmt.Sprintf("%s (relay log incomplete: %v)", strings.TrimSpace(lr.stderr), err)
		}
		return strings.TrimSpace(lr.stderr)
	}

	script := fmt.Sprintf(`import os, signal, socket, time
for i in range(200):
    try:
        c = socket.create_connection(("127.0.0.1", 13128)); break
    except OSError:
        time.sleep(0.02)
c.sendall(b"ping-relay"); print(c.recv(100).decode())
os.kill(%d, signal.SIGHUP)
c.settimeout(5)
try:
    d = c.recv(10); print("after-hup:", "eof" if d == b"" else d)
except ConnectionResetError:
    print("after-hup: reset")
c2 = socket.create_connection(("127.0.0.1", 13128)); c2.sendall(b"again"); print(c2.recv(100).decode())
`, relayPID)
	r, err := run(kctx, c, &pb.Command{Argv: []string{"/usr/local/bin/python3", "-c", script}})
	if err != nil {
		t.Fatal(err)
	}
	if r.stdout != "ping-relay\nafter-hup: reset\nagain\n" {
		t.Fatalf("relay client: %q %q\nrelay log: %s", r.stdout, r.stderr, relayLog())
	}
	select {
	case <-upEnded:
	case <-time.After(5 * time.Second):
		t.Fatal("host side of the reset connection stayed open")
	}
	t.Logf("relay log: %s", relayLog())
}
