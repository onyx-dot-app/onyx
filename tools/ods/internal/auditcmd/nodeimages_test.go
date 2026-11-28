package auditcmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

type nodeFeedTransport struct{ fail bool }

func (transport *nodeFeedTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	body := ""
	switch req.URL.Path {
	case "/dist/index.json":
		if transport.fail {
			return nil, fmt.Errorf("release feed unavailable")
		}
		body = `[{"version":"v24.16.0"},{"version":"v24.22.3","security":true}]`
	case "/nodejs/security-wg/main/vuln/core/index.json":
		body = `{"1":{"vulnerable":"24.x","patched":"^24.22.3","severity":"critical","cve":["CVE-2099-12345"]}}`
	default:
		return nil, fmt.Errorf("unexpected feed %s", req.URL)
	}
	return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(body))}, nil
}

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
	pinned := image
	image = "node:24@sha256:" + strings.Repeat("b", 64)
	if out, err := run(); err == nil || out != "" || !strings.Contains(err.Error(), "absent") {
		t.Fatalf("missing web digest: output=%q err=%v", out, err)
	}
	image = pinned
	bin := fakeBinDir(t)
	docker := writeFakeCommand(t, bin, "docker", `[ -n "$TEST_NODE_VERSION" ] || exit 1
echo "$TEST_NODE_VERSION"`)
	original := http.DefaultTransport
	feeds := &nodeFeedTransport{}
	http.DefaultTransport = feeds
	t.Cleanup(func() { http.DefaultTransport = original })
	for _, tc := range []struct {
		version string
		blocked int
	}{{"v24.16.0", 2}, {"v24.22.3", 0}} {
		t.Setenv("TEST_NODE_VERSION", tc.version)
		out, err := run()
		var report audit.Result
		if err != nil || json.Unmarshal([]byte(out), &report) != nil || len(report.Blocking) != tc.blocked || len(report.ScannedPackages) != 1 {
			t.Fatalf("%s: output=%q err=%v", tc.version, out, err)
		}
		for _, f := range report.Blocking {
			if f.Manifest != "Dockerfile" || f.Image != image {
				t.Fatalf("wrong source: %+v", f)
			}
		}
	}
	if calls := docker(); len(calls) != 2 || !strings.Contains(calls[0], image+" --version") {
		t.Fatalf("unexpected docker calls %v", calls)
	}
	feeds.fail = true
	if out, err := run(); err == nil || out != "" {
		t.Fatalf("missing feed: output=%q err=%v", out, err)
	}
	feeds.fail = false
	t.Setenv("TEST_NODE_VERSION", "")
	if out, err := run(); err == nil || out != "" {
		t.Fatalf("failed probe: output=%q err=%v", out, err)
	}
}
