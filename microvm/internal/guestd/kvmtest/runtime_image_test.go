//go:build kvm && linux

package kvmtest

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

func TestRuntimeImageKVM(t *testing.T) {
	if os.Getenv("KVM_RUNTIME_IMAGE") != "1" {
		t.Skip("set KVM_RUNTIME_IMAGE=1 with a craft-runtime rootfs")
	}
	e := loadEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	v := bootVM(t, e, "runtime-image", "")
	if _, err := waitHealth(ctx, v); err != nil {
		t.Fatalf("health: %v\n%s", err, v.console())
	}
	c, _ := client(t, v)
	key := randHex(32)
	if _, err := keyInit(ctx, c, key, initRequest("runtime-image")); err != nil {
		t.Fatal(err)
	}
	result, err := run(keyed(ctx, key), c, &pb.Command{Argv: []string{"/opt/onyx/check-runtime"}})
	t.Logf("stdout:\n%s\nstderr:\n%s", result.stdout, result.stderr)
	if err != nil || result.res.GetCompletion() != pb.Completion_EXITED || result.res.GetExitCode() != 0 || !strings.Contains(result.stdout, "Craft runtime smoke checks passed.") {
		t.Fatalf("runtime image check: error=%v result=%v", err, result.res)
	}
}
