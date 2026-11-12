//go:build !windows

package cmd

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

func TestStackSetupKeepsStdoutClean(t *testing.T) {
	_, _ = stackTestRepo(t)
	bun, err := exec.LookPath("bun")
	if err != nil {
		t.Fatal(err)
	}
	devtoolFakeTool(t, filepath.Dir(bun), "bun", "echo bun-progress\n")
	devtoolFakeTool(t, filepath.Dir(bun), "docker", "echo compose-progress\n")
	_, provider := openStack(nil)
	output, err := os.CreateTemp(t.TempDir(), "stdout")
	if err != nil {
		t.Fatal(err)
	}
	original := os.Stdout
	os.Stdout = output
	t.Cleanup(func() { os.Stdout = original; _ = output.Close() })
	if err := provider.Prepare(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := provider.ComposeUp(context.Background(), map[string]int{"POSTGRES_HOST_PORT": 5555}, devstack.Options{}); err != nil {
		t.Fatal(err)
	}
	os.Stdout = original
	data, err := os.ReadFile(output.Name())
	if err != nil {
		t.Fatal(err)
	}
	if len(data) != 0 {
		t.Fatalf("setup polluted JSON stdout: %q", data)
	}
}
