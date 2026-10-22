package cmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
)

// deployGHReply is one canned response of the fake gh binary.
type deployGHReply struct {
	stdout string
	stderr string
	exit   int
}

// deployFakeGH is a fake gh binary that records every call and answers from
// canned replies.
type deployFakeGH struct {
	t   *testing.T
	dir string
}

// deployGHScript picks the reply list by gh subcommand and serves the replies
// in order, repeating the last one once the list runs out. `gh --version`
// always succeeds so git.CheckGitHubCLI passes.
const deployGHScript = `#!/bin/sh
d=$(dirname "$0")
printf '%s\n' "$*" >> "$d/calls"
case "$1 $2" in
  "run list") key=run-list ;;
  "run view") case "$*" in *"--json jobs"*) key=run-jobs ;; *) key=run-view ;; esac ;;
  "workflow run") key=workflow-run ;;
  "pr list") key=pr-list ;;
  *) exit 0 ;;
esac
n=$(( $(cat "$d/$key.count" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$d/$key.count"
max=$(cat "$d/$key.max" 2>/dev/null || echo 0)
if [ "$max" -eq 0 ]; then
  echo "unexpected gh call: $*" >&2
  exit 97
fi
[ "$n" -gt "$max" ] && n=$max
cat "$d/$key.$n.out"
cat "$d/$key.$n.err" >&2
exit "$(cat "$d/$key.$n.code")"
`

// deployNewFakeGH puts a fake gh first on PATH. The keys of replies are
// "run-list", "run-view" (a single run), "run-jobs" (a run's jobs),
// "workflow-run" and "pr-list".
func deployNewFakeGH(t *testing.T, replies map[string][]deployGHReply) *deployFakeGH {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake gh is a shell script")
	}
	dir := t.TempDir()
	for key, list := range replies {
		for i, reply := range list {
			base := filepath.Join(dir, fmt.Sprintf("%s.%d", key, i+1))
			deployWriteFile(t, base+".out", reply.stdout)
			deployWriteFile(t, base+".err", reply.stderr)
			deployWriteFile(t, base+".code", fmt.Sprintf("%d", reply.exit))
		}
		deployWriteFile(t, filepath.Join(dir, key+".max"), fmt.Sprintf("%d", len(list)))
	}
	if err := os.WriteFile(filepath.Join(dir, "gh"), []byte(deployGHScript), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	return &deployFakeGH{t: t, dir: dir}
}

// calls returns the argv of every gh call, space-joined, in call order.
func (g *deployFakeGH) calls() []string {
	g.t.Helper()
	data, err := os.ReadFile(filepath.Join(g.dir, "calls"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		g.t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

func deployWriteFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// deployRuns renders runs as `gh run list --json` output.
func deployRuns(t *testing.T, runs ...workflowRun) deployGHReply {
	t.Helper()
	if runs == nil {
		runs = []workflowRun{}
	}
	data, err := json.Marshal(runs)
	if err != nil {
		t.Fatal(err)
	}
	return deployGHReply{stdout: string(data)}
}

// deployRun renders a single run as `gh run view --json` output.
func deployRun(t *testing.T, run workflowRun) deployGHReply {
	t.Helper()
	data, err := json.Marshal(run)
	if err != nil {
		t.Fatal(err)
	}
	return deployGHReply{stdout: string(data)}
}

func deployGHFailure(stderr string) deployGHReply {
	return deployGHReply{stderr: stderr, exit: 1}
}

// deployFastPolling keeps poll loops from sleeping for real intervals.
func deployFastPolling() runPolling {
	return runPolling{
		discoveryInterval: time.Millisecond,
		discoveryTimeout:  500 * time.Millisecond,
		progressInterval:  time.Millisecond,
		bumpPRInterval:    time.Millisecond,
		bumpPRTimeout:     500 * time.Millisecond,
	}
}

// deployIsolateConfig points the ods config at a temp dir and returns the
// config file path.
func deployIsolateConfig(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv("HOME", t.TempDir())
	return filepath.Join(dir, "onyx-dev", "config.json")
}

func deploySaveConfig(t *testing.T, cfg *config.Config) {
	t.Helper()
	if err := config.Save(cfg); err != nil {
		t.Fatal(err)
	}
}

// deployOutput holds the stdout and logrus output captured for one test.
type deployOutput struct {
	stdout *os.File
	logs   *bytes.Buffer
}

func deployCaptureOutput(t *testing.T) *deployOutput {
	t.Helper()
	f, err := os.CreateTemp(t.TempDir(), "stdout")
	if err != nil {
		t.Fatal(err)
	}
	origStdout := os.Stdout
	origLog := log.StandardLogger().Out
	logs := &bytes.Buffer{}
	os.Stdout = f
	log.SetOutput(logs)
	t.Cleanup(func() {
		os.Stdout = origStdout
		log.SetOutput(origLog)
		_ = f.Close()
	})
	return &deployOutput{stdout: f, logs: logs}
}

func (o *deployOutput) printed(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(o.stdout.Name())
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}
