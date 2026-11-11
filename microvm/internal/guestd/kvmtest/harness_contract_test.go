//go:build kvm && linux

package kvmtest

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/status"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// harnessMount is one managed mount of the layout 5 drive order.
type harnessMount struct {
	name, a, b string // mount name, slot A and slot B drive IDs
}

var harnessMounts = []harnessMount{
	{"skills", "managed", "managed_b"},
	{"user-uploads", "user_uploads_a", "user_uploads_b"},
	{"spaces", "spaces_a", "spaces_b"},
}

// mkfsDir makes an ext4 image at path with one file, marker, holding text,
// and an executable script run.sh. It returns the image size.
func mkfsDir(t *testing.T, path, uuid, text string) uint64 {
	t.Helper()
	src := t.TempDir()
	if err := os.WriteFile(filepath.Join(src, "marker"), []byte(text+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "run.sh"), []byte("#!/bin/sh\necho ran\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command("mkfs.ext4", "-q", "-F", "-m", "0", "-O", "^has_journal", "-U", uuid,
		"-E", "root_owner=0:0", "-d", src, path, "8M").CombinedOutput(); err != nil {
		t.Fatalf("mkfs %s: %v %s", path, err, out)
	}
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	return uint64(st.Size())
}

// bootHarnessVM cold boots a VM with the ten drives of template layout 5:
// rootfs, scratch, skills A, upload A/B, skills B, then the A and B slots of
// user-uploads and spaces. Slot A of each mount has marker "a-<mount>".
func bootHarnessVM(t *testing.T, e env, name string) *vm {
	t.Helper()
	dir := prepareDir(t, e, name)
	file := func(id string) string { return id + ".ext4" }
	drives := []map[string]any{
		{"drive_id": "rootfs", "path_on_host": "rootfs.ext4", "is_root_device": true, "is_read_only": true},
		{"drive_id": "scratch", "path_on_host": "scratch.ext4", "is_root_device": false, "is_read_only": false},
	}
	ro := func(id string) map[string]any {
		return map[string]any{"drive_id": id, "path_on_host": file(id), "is_root_device": false, "is_read_only": true}
	}
	for _, id := range []string{"upload_a", "upload_b", "managed_b", "user_uploads_b", "spaces_b"} {
		if err := os.WriteFile(filepath.Join(dir, file(id)), make([]byte, 1<<20), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for i, m := range harnessMounts {
		mkfsDir(t, filepath.Join(dir, file(m.a)), fmt.Sprintf("aaaaaaaa-0000-4000-8000-00000000000%d", i), "a-"+m.name)
	}
	for _, id := range []string{"managed", "upload_a", "upload_b", "managed_b", "user_uploads_a", "user_uploads_b", "spaces_a", "spaces_b"} {
		drives = append(drives, ro(id))
	}
	cfg := map[string]any{
		"boot-source":    map[string]any{"kernel_image_path": "vmlinux", "boot_args": e.BootArgs},
		"drives":         drives,
		"machine-config": map[string]any{"vcpu_count": 2, "mem_size_mib": vmMemMiB},
		"vsock":          map[string]any{"guest_cid": 3, "uds_path": "v.sock"},
	}
	writeJSON(t, filepath.Join(dir, "config.json"), cfg)
	return startFC(t, e, dir, "--config-file", "config.json")
}

// TestHarnessContractKVM checks the guest side of the harness contract on
// the production root drive: the session directory and unscoped commands,
// the command env, Cancel with SIGINT to the process group, the execution
// cap, and a swap of each of the three managed mounts.
func TestHarnessContractKVM(t *testing.T) {
	e := loadEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	v := bootHarnessVM(t, e, "harness")
	if _, err := waitHealth(ctx, v); err != nil {
		t.Fatalf("%v\nconsole: %s", err, v.console())
	}
	c, _ := client(t, v)
	key := randHex(32)
	if _, err := keyInit(ctx, c, key, initRequest("harness")); err != nil {
		t.Fatal(err)
	}
	kctx := keyed(ctx, key)

	t.Run("session_dir_and_unscoped_commands", func(t *testing.T) {
		r, err := run(kctx, c, &pb.Command{Argv: []string{"sh", "-c", `pwd
stat -c '%U:%G %a' /home/onyx /home/onyx/workspaces
echo other > /home/onyx/workspaces/s2-file && cat /home/onyx/workspaces/s2-file
echo tmp > /tmp/harness && cat /tmp/harness
cd /etc && pwd`}, SessionId: "s1"})
		t.Logf("stdout:\n%s stderr: %s", r.stdout, r.stderr)
		want := "/home/onyx/workspaces/s1\nsandbox:sandbox 755\nsandbox:sandbox 755\nother\ntmp\n/etc\n"
		if err != nil || r.res.GetExitCode() != 0 || r.stdout != want {
			t.Fatalf("got %q (%v %v), want %q", r.stdout, err, r.res, want)
		}
		// File calls with no session reach any VM path, but not the daemon state.
		rs, err := c.ReadFile(kctx, &pb.ReadFileRequest{Path: "/tmp/harness"})
		if err != nil {
			t.Fatal(err)
		}
		if info, err := rs.Recv(); err != nil || info.GetInfo().GetPath() != "/tmp/harness" {
			t.Fatalf("read /tmp: %v %v", info, err)
		}
		if d, err := rs.Recv(); err != nil || string(d.GetData()) != "tmp\n" {
			t.Fatalf("read /tmp data: %v %v", d, err)
		}
		rs, _ = c.ReadFile(kctx, &pb.ReadFileRequest{Path: "/run/craft-fc/guest-daemon-init.json"})
		if _, err := rs.Recv(); reasonOf(err) != "INVALID_ARGUMENT" {
			t.Fatalf("daemon state: %v", err)
		}
	})

	t.Run("command_env", func(t *testing.T) {
		r, err := run(kctx, c, &pb.Command{Argv: []string{"sh", "-c",
			`echo "$NO_COLOR $TERM $PAGER $GIT_PAGER $GH_PAGER $LANG $LC_ALL"; python3 -c 'import sys; print(sys.stdout.encoding)'`}})
		if err != nil || r.stdout != "1 dumb cat cat cat C.UTF-8 C.UTF-8\nutf-8\n" {
			t.Fatalf("env %q %q %v", r.stdout, r.stderr, err)
		}
	})

	t.Run("cancel_sigint_process_group", func(t *testing.T) {
		// Ctrl-C: bash handles it, its foreground child (sleep) dies of it.
		st, err := c.Start(kctx, &pb.StartRequest{Command: &pb.Command{SessionId: "s1",
			Argv: []string{"bash", "-c", `trap 'echo shell-int' INT; echo ready; sleep 300; echo "sleep-rc $?"`}}})
		if err != nil {
			t.Fatal(err)
		}
		id := st.GetStarted().GetExecutionId()
		waitStdout(ctx, t, c, key, id, "ready")
		time.Sleep(200 * time.Millisecond)
		cr, err := c.Cancel(kctx, &pb.CancelRequest{ExecutionId: id, Signal: pb.CancelSignal_CANCEL_SIGNAL_SIGINT})
		if err != nil || !cr.GetSignaled() || cr.GetResult() != nil {
			t.Fatalf("cancel: %v %v", cr, err)
		}
		r := streamAll(ctx, t, c, key, id)
		if r.res.GetCompletion() != pb.Completion_EXITED || r.res.GetExitCode() != 0 || !strings.Contains(r.stdout, "shell-int") ||
			!strings.Contains(r.stdout, "sleep-rc 130") {
			t.Fatalf("handled SIGINT: %q %v", r.stdout, r.res)
		}
		// Python gets KeyboardInterrupt.
		st, _ = c.Start(kctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"python3", "-u", "-c",
			"import time\nprint('ready')\ntry:\n    time.sleep(300)\nexcept KeyboardInterrupt:\n    print('kbi')\n"}}})
		id = st.GetStarted().GetExecutionId()
		waitStdout(ctx, t, c, key, id, "ready")
		if _, err := c.Cancel(kctx, &pb.CancelRequest{ExecutionId: id, Signal: pb.CancelSignal_CANCEL_SIGNAL_SIGINT}); err != nil {
			t.Fatal(err)
		}
		if r := streamAll(ctx, t, c, key, id); r.stdout != "ready\nkbi\n" || r.res.GetExitCode() != 0 {
			t.Fatalf("python: %q %v", r.stdout, r.res)
		}
		// A command that dies of the signal is CANCELED.
		st, _ = c.Start(kctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"sleep", "300"}}})
		id = st.GetStarted().GetExecutionId()
		if _, err := c.Cancel(kctx, &pb.CancelRequest{ExecutionId: id, Signal: pb.CancelSignal_CANCEL_SIGNAL_SIGINT}); err != nil {
			t.Fatal(err)
		}
		if r := streamAll(ctx, t, c, key, id); r.res.GetCompletion() != pb.Completion_CANCELED || r.res.GetSignal() != 2 {
			t.Fatalf("sleep: %v", r.res)
		}
	})

	t.Run("execution_cap", func(t *testing.T) {
		var ids []string
		for range 64 {
			st, err := c.Start(kctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"sleep", "300"}}})
			if err != nil {
				t.Fatalf("start %d: %v", len(ids), err)
			}
			ids = append(ids, st.GetStarted().GetExecutionId())
		}
		if _, err := c.Start(kctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"true"}}}); reasonOf(err) != "EXECUTION_CAP_REACHED" {
			t.Fatalf("65th: %v", err)
		}
		l, err := c.List(kctx, &pb.ListRequest{})
		if err != nil || len(l.GetExecutions()) != 64 {
			t.Fatalf("list: %d %v", len(l.GetExecutions()), err)
		}
		for _, id := range ids {
			if _, err := c.Cancel(kctx, &pb.CancelRequest{ExecutionId: id}); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := c.Start(kctx, &pb.StartRequest{Command: &pb.Command{Argv: []string{"true"}}}); err != nil {
			t.Fatalf("after cancel: %v", err)
		}
	})

	t.Run("three_managed_mounts_swap", func(t *testing.T) {
		check := func(want map[string]string) {
			t.Helper()
			var script strings.Builder
			for _, m := range harnessMounts {
				fmt.Fprintf(&script, "cat /mnt/%s/marker; grep ' /mnt/%s ' /proc/mounts | cut -d' ' -f4 | tr , '\\n' | grep -cxE 'ro|noexec|nodev|nosuid'; touch /mnt/%s/x 2>/dev/null && echo WRITABLE; /mnt/%s/run.sh 2>/dev/null && echo EXEC; sh /mnt/%s/run.sh\n",
					m.name, m.name, m.name, m.name, m.name)
			}
			out := rootSh(ctx, t, c, key, script.String())
			var exp strings.Builder
			for _, m := range harnessMounts {
				fmt.Fprintf(&exp, "%s\n4\nran\n", want[m.name])
			}
			if out != exp.String() {
				t.Fatalf("mounts:\n%s\nwant:\n%s", out, exp.String())
			}
		}
		want := map[string]string{}
		for _, m := range harnessMounts {
			want[m.name] = "a-" + m.name
		}
		check(want)
		for i, m := range harnessMounts {
			uuid := fmt.Sprintf("bbbbbbbb-0000-4000-8000-00000000000%d", i)
			img := filepath.Join(v.dir, m.b+"-new.ext4")
			size := mkfsDir(t, img, uuid, "b-"+m.name)
			if err := fcAPI(ctx, v.dir, http.MethodPatch, "/drives/"+m.b, map[string]any{"drive_id": m.b, "path_on_host": filepath.Base(img)}); err != nil {
				t.Fatalf("%s: %v", m.name, err)
			}
			st, err := c.ManagedStatus(kctx, &pb.ManagedStatusRequest{Mount: m.name})
			if err != nil || st.GetMount() != m.name || st.GetMountPoint() != "/mnt/"+m.name || st.GetActive() != pb.ManagedSlot_MANAGED_SLOT_A {
				t.Fatalf("%s status: %v %v", m.name, st, err)
			}
			mr, err := c.MountManaged(kctx, &pb.MountManagedRequest{Mount: m.name, Slot: pb.ManagedSlot_MANAGED_SLOT_B, SizeBytes: size, FsUuid: uuid})
			if err != nil || mr.GetActive() != pb.ManagedSlot_MANAGED_SLOT_B || !mr.GetChanged() || mr.GetMount() != m.name {
				t.Fatalf("%s mount: %v %v", m.name, mr, err)
			}
			t.Logf("%s swapped (size wait %d ms)", m.name, mr.GetWaitMs())
			want[m.name] = "b-" + m.name
			check(want) // only this mount changed
		}
	})
}

// reasonOf is the ErrorInfo reason of a daemon error.
func reasonOf(err error) string {
	st, _ := status.FromError(err)
	for _, d := range st.Details() {
		if info, ok := d.(*errdetails.ErrorInfo); ok {
			return info.GetReason()
		}
	}
	return ""
}

func writeJSON(t *testing.T, path string, v map[string]any) {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
}

// waitStdout streams execution id until stdout has want.
func waitStdout(ctx context.Context, t *testing.T, c pb.SandboxdClient, key, id, want string) {
	t.Helper()
	sctx, cancel := context.WithTimeout(keyed(ctx, key), 30*time.Second)
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

// streamAll streams execution id from the start to its result.
func streamAll(ctx context.Context, t *testing.T, c pb.SandboxdClient, key, id string) result {
	t.Helper()
	sctx, cancel := context.WithTimeout(keyed(ctx, key), 30*time.Second)
	defer cancel()
	s, err := c.Stream(sctx, &pb.StreamRequest{ExecutionId: id})
	if err != nil {
		t.Fatal(err)
	}
	r, err := collect(s)
	if err != nil && err != io.EOF {
		t.Fatalf("stream %s: %v", id, err)
	}
	return r
}
