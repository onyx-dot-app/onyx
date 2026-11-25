package auditcmd

import (
	"bytes"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestNodeImagesCommand(t *testing.T) {
	dir := chdirNewRepo(t)
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
	writeFixture(t, dir, "Dockerfile", "FROM "+image+"\n")
	gittest.Git(t, dir, "add", "Dockerfile")
	if out, err := run(); err != nil || !strings.Contains(out, `"blocking"`) {
		t.Fatalf("web-only inventory: output=%q err=%v", out, err)
	}
}
