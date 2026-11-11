//go:build kvm && linux

package kvmtest

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// bootDrives cold boots a VM with the rootfs and, if set, the scratch and
// managed drives.
func bootDrives(t *testing.T, e env, name string, scratch, managed bool) *vm {
	t.Helper()
	dir := prepareDir(t, e, name)
	drives := []map[string]any{{"drive_id": "rootfs", "path_on_host": "rootfs.ext4", "is_root_device": true, "is_read_only": true}}
	if scratch {
		drives = append(drives, map[string]any{"drive_id": "scratch", "path_on_host": "scratch.ext4", "is_root_device": false, "is_read_only": false})
	}
	if _, err := os.Stat(filepath.Join(dir, "managed-empty.ext4")); managed && err == nil {
		drives = append(drives, map[string]any{"drive_id": "managed", "path_on_host": "managed-empty.ext4", "is_root_device": false, "is_read_only": true})
	}
	cfg := map[string]any{
		"boot-source":    map[string]any{"kernel_image_path": "vmlinux", "boot_args": e.BootArgs},
		"drives":         drives,
		"machine-config": map[string]any{"vcpu_count": 2, "mem_size_mib": vmMemMiB},
		"vsock":          map[string]any{"guest_cid": 3, "uds_path": "v.sock"},
	}
	raw, _ := json.Marshal(cfg)
	if err := os.WriteFile(filepath.Join(dir, "config.json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return startFC(t, e, dir, "--config-file", "config.json")
}

// rootSh runs script as root in the VM and returns its stdout.
func rootSh(ctx context.Context, t *testing.T, c pb.SandboxdClient, key, script string) string {
	t.Helper()
	r, err := run(keyed(ctx, key), c, sh(script))
	if err != nil {
		t.Fatalf("%q: %v", script, err)
	}
	return r.stdout
}

// waitFor runs script until its trimmed stdout is want, for up to 30 s.
func waitFor(ctx context.Context, t *testing.T, c pb.SandboxdClient, key, script, want string) string {
	t.Helper()
	var got string
	for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(200 * time.Millisecond) {
		r, err := run(keyed(ctx, key), c, sh(script))
		if err == nil {
			if got = strings.TrimSpace(r.stdout); got == want {
				return got
			}
		}
	}
	t.Fatalf("%q: got %q, want %q", script, got, want)
	return ""
}

// TestInitKVM checks the VM init (deployment/craft-fc/rootfs/craft-init) on
// cold boots: fail-closed attach, the managed fallback, the relay's
// privileges, restarts that never run helpers from the overlays, and the log
// cap.
func TestInitKVM(t *testing.T) {
	e := loadEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	t.Run("no_scratch_starts_no_service", func(t *testing.T) {
		v := bootDrives(t, e, "init-noscratch", false, false)
		hctx, hcancel := context.WithTimeout(ctx, 90*time.Second)
		defer hcancel()
		health := make(chan error, 1)
		go func() {
			_, err := waitHealth(hctx, v)
			health <- err
		}()
		ticker := time.NewTicker(50 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case err := <-health:
				if err == nil {
					t.Fatal("daemon answered with a failed attach")
				}
				t.Fatalf("no attach failure before health probe ended: %v\n%s", err, v.console())
			case <-hctx.Done():
				t.Fatalf("no attach failure on the console:\n%s", v.console())
			case <-ticker.C:
				if strings.Contains(v.console(), "attach failed") {
					hcancel()
					if err := <-health; err == nil {
						t.Fatal("daemon answered with a failed attach")
					}
					t.Log("no scratch drive: daemon did not start (fail closed)")
					return
				}
			}
		}
	})

	v := bootDrives(t, e, "init-main", true, false)
	if _, err := waitHealth(ctx, v); err != nil {
		t.Fatalf("%v\nconsole: %s", err, v.console())
	}
	parent := t
	c, _ := client(t, v)
	key := randHex(32)
	if _, err := keyInit(ctx, c, key, initRequest("init-main")); err != nil {
		t.Fatal(err)
	}

	t.Run("no_managed_drive_is_read_only_tmpfs", func(t *testing.T) {
		out := rootSh(ctx, t, c, key, `grep ' /workspace/managed ' /proc/mounts | cut -d' ' -f1,3,4 | cut -d, -f1; touch /workspace/managed/x 2>/dev/null && echo WRITABLE || echo READONLY`)
		t.Logf("managed mount: %q", out)
		if !strings.Contains(out, "craft-managed-empty tmpfs ro") || !strings.Contains(out, "READONLY") {
			t.Errorf("managed fallback: %q", out)
		}
	})

	t.Run("relay_privileges", func(t *testing.T) {
		out := rootSh(ctx, t, c, key, `p=$(cat /run/craft-fc/egress-relay.pid); grep -E '^(Uid|Gid|Groups|CapPrm|CapEff|CapAmb|NoNewPrivs):' /proc/$p/status; readlink /proc/$p/exe`)
		t.Logf("relay:\n%s", out)
		for _, want := range []string{"Uid:\t65534\t65534\t65534\t65534", "Gid:\t65534\t65534\t65534\t65534", "CapPrm:\t0000000000000000",
			"CapEff:\t0000000000000000", "CapAmb:\t0000000000000000", "NoNewPrivs:\t1", "/craft-fc/bin/egress-relay"} {
			if !strings.Contains(out, want) {
				t.Errorf("relay status has no %q", want)
			}
		}
		if g := strings.TrimSpace(strings.SplitN(strings.SplitN(out, "Groups:", 2)[1], "\n", 2)[0]); g != "" {
			t.Errorf("relay has supplementary groups %q", g)
		}
	})

	t.Run("restart_never_runs_overlay_helpers", func(t *testing.T) {
		// Fakes for every helper the old init found through PATH, in the
		// writable /usr overlay and in the sandbox-owned venv.
		plant := `bb=/craft-fc/bin/busybox
for d in /usr/bin /usr/local/bin /usr/sbin /workspace/.venv/bin; do
  [ -d $d ] || continue
  for n in env setpriv nsenter stat mv cp sleep date; do
    [ -e $d/$n ] && $bb cp -a $d/$n /tmp/orig-$(echo $d | $bb tr / _)-$n
    printf '#!/bin/sh\ntouch /tmp/pwned-%s\n' $n >$d/$n.fake && $bb chmod 0755 $d/$n.fake && $bb mv -f $d/$n.fake $d/$n
  done
done; echo planted`
		// Call busybox applets by path, so a fake planted earlier in the loop
		// never runs.
		if r, err := run(keyed(ctx, key), c, &pb.Command{Argv: []string{"/craft-fc/bin/busybox", "sh", "-c", plant}}); err != nil || !strings.Contains(r.stdout, "planted") {
			t.Fatalf("plant: %v %q %q", err, r.stdout, r.stderr)
		}
		old := strings.TrimSpace(rootSh(ctx, t, c, key, `cat /run/craft-fc/egress-relay.pid`))
		rootSh(ctx, t, c, key, `kill -9 $(cat /run/craft-fc/egress-relay.pid)`)
		waitFor(ctx, t, c, key, `p=$(cat /run/craft-fc/egress-relay.pid); [ "$p" != "`+old+`" ] && [ "$(readlink /proc/$p/exe)" = /craft-fc/bin/egress-relay ] && echo up`, "up")

		// The daemon restarts too, and keeps its Init state (key).
		_, _ = run(keyed(ctx, key), c, sh(`kill -9 $(cat /run/craft-fc/guest-daemon.pid)`))
		hctx, hcancel := context.WithTimeout(ctx, 30*time.Second)
		defer hcancel()
		h, err := waitHealth(hctx, v)
		if err != nil || !h.GetInitialized() {
			t.Fatalf("daemon after kill -9: %v %v", h, err)
		}
		// The new connection outlives this subtest.
		c2, _ := client(parent, v)
		c = c2
		out := rootSh(ctx, t, c, key, `ls /tmp/pwned-* 2>/dev/null | wc -l; grep -c 'started' /run/craft-fc/init.log`)
		t.Logf("after relay and daemon restarts (marker files, start lines): %q", out)
		if strings.Fields(out)[0] != "0" {
			t.Errorf("a restart ran a helper from the overlays: %q", rootSh(ctx, t, c, key, `ls /tmp/pwned-*`))
		}
	})

	t.Run("log_cap", func(t *testing.T) {
		rootSh(ctx, t, c, key, `head -c 6000000 /dev/zero | tr '\0' x >>/run/craft-fc/log/egress-relay.log; echo ok`)
		got := waitFor(ctx, t, c, key, `s=$(wc -c </run/craft-fc/log/egress-relay.log); [ "$s" -lt 4194304 ] && [ -f /run/craft-fc/log/egress-relay.log.1 ] && echo capped`, "capped")
		t.Logf("relay log: %s", got)
	})

	t.Run("managed_unmount_keeps_drive", func(t *testing.T) {
		m := bootDrives(t, e, "init-managed", true, true)
		if _, err := waitHealth(ctx, m); err != nil {
			t.Fatalf("%v\nconsole: %s", err, m.console())
		}
		mc, _ := client(t, m)
		mkey := randHex(32)
		if _, err := keyInit(ctx, mc, mkey, initRequest("init-managed")); err != nil {
			t.Fatal(err)
		}
		out := rootSh(ctx, t, mc, mkey, `grep ' /workspace/managed ' /proc/mounts | cut -d' ' -f1,4 | cut -d, -f1
touch /workspace/managed/x 2>/dev/null && echo WRITABLE || echo READONLY
mount -o remount,rw /workspace/managed 2>/dev/null && echo REMOUNT_RW || echo REMOUNT_REFUSED
umount /workspace/managed && echo hello >/workspace/managed/f && echo WROTE_BELOW
mkdir -p /tmp/m && mount -o ro,noload /dev/vdc /tmp/m && { [ -e /tmp/m/f ] && echo ON_DRIVE || echo NOT_ON_DRIVE; }`)
		t.Logf("managed drive:\n%s", out)
		for _, want := range []string{"/dev/vdc ro", "READONLY", "REMOUNT_REFUSED", "NOT_ON_DRIVE"} {
			if !strings.Contains(out, want) {
				t.Errorf("managed drive: no %q", want)
			}
		}
	})
}
