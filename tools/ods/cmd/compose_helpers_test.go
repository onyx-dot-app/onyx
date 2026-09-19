package cmd

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// composeFakeBin creates a directory for fake tools and puts it at the front
// of PATH, so the fakes shadow any real docker or devcontainer while git stays
// reachable.
func composeFakeBin(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake tools are shell scripts")
	}
	bin := t.TempDir()
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	return bin
}

// composeFakeTool writes an executable script called name into bin. The script
// appends its argv as one line to <bin>/<name>.calls and then runs body.
func composeFakeTool(t *testing.T, bin, name, body string) {
	t.Helper()
	script := "#!/bin/sh\necho \"$*\" >> \"" + filepath.Join(bin, name+".calls") + "\"\n" + body + "\n"
	if err := os.WriteFile(filepath.Join(bin, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
}

// composeCalls returns the argv lines the fake tool recorded, or nil if it was
// never run.
func composeCalls(t *testing.T, bin, name string) []string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(bin, name+".calls"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

// composeRepo creates an empty git repository named ods-proj (so the compose
// project name is "ods-proj") with a deployment/docker_compose directory, makes
// it the working directory, and returns its root as git reports it.
func composeRepo(t *testing.T) string {
	t.Helper()
	docker.SetProjectFlags("")
	t.Cleanup(func() { docker.SetProjectFlags("") })

	// Keep git away from the developer's config (for example commit signing).
	t.Setenv("GIT_CONFIG_GLOBAL", filepath.Join(t.TempDir(), "gitconfig"))
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	for _, key := range []string{"GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"} {
		t.Setenv(key, "ods test")
	}
	for _, key := range []string{"GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"} {
		t.Setenv(key, "ods@example.com")
	}

	root := filepath.Join(t.TempDir(), "ods-proj")
	if err := os.MkdirAll(filepath.Join(root, "deployment", "docker_compose"), 0o755); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, root, "init")
	t.Chdir(root)

	resolved, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	return resolved
}

// composeNoRepo makes a directory outside any git repository the working
// directory.
func composeNoRepo(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)
}

func composeReadFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// composeCaptureLog sends logrus output to the returned buffer until the test
// ends. Each entry has the form "level=<level> msg=<message>".
func composeCaptureLog(t *testing.T) *bytes.Buffer {
	t.Helper()
	restoreLogger(t)
	logger := log.StandardLogger()
	var buf bytes.Buffer
	logger.SetOutput(&buf)
	logger.SetFormatter(&log.TextFormatter{DisableTimestamp: true, DisableQuote: true})
	logger.SetLevel(log.InfoLevel)
	return &buf
}

// composeCapture replaces *stream (os.Stdout or os.Stderr) with a pipe while fn
// runs and returns what fn wrote to it. The stream is restored even when fn
// fails the test.
func composeCapture(t *testing.T, stream **os.File, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	original := *stream
	*stream = w
	defer func() {
		*stream = original
		_ = w.Close()
		_ = r.Close()
	}()

	done := make(chan string, 1)
	go func() {
		data, _ := io.ReadAll(r)
		done <- string(data)
	}()

	fn()
	*stream = original
	_ = w.Close()
	return <-done
}
