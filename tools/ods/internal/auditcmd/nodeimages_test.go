package auditcmd

import (
	"bytes"
	"os"
	"os/exec"
	"strings"
	"testing"
)

func TestNodeImagesCommand(t *testing.T) {
	t.Chdir(t.TempDir())
	if out, err := exec.Command("git", "init", "-q").CombinedOutput(); err != nil {
		t.Fatalf("git init: %s: %v", out, err)
	}
	digest := "sha256:" + strings.Repeat("a", 64)
	image := "dhi.io/node:24@" + digest
	run := func() (string, error) {
		cmd := NewRootCommand("test", "test")
		var out bytes.Buffer
		cmd.SetOut(&out)
		cmd.SetArgs([]string{"node-images", image})
		cmd.SilenceUsage = true
		cmd.SilenceErrors = true
		err := cmd.Execute()
		return out.String(), err
	}
	if out, err := run(); err == nil || out != "" {
		t.Fatalf("empty inventory: output=%q err=%v", out, err)
	}
	if err := os.WriteFile("Dockerfile", []byte("FROM "+image+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command("git", "add", "Dockerfile").CombinedOutput(); err != nil {
		t.Fatalf("git add: %s: %v", out, err)
	}
	if out, err := run(); err != nil || !strings.Contains(out, `"blocking"`) {
		t.Fatalf("web-only inventory: output=%q err=%v", out, err)
	}
}
