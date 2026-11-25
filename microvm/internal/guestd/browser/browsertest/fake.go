// Package browsertest turns a test binary into a fake Chrome for tests of
// the browser package and its callers.
package browsertest

import (
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// EnvMode selects the fake: ModeServe or ModeFail. A process without it
// is not a fake.
const EnvMode = "GUESTD_FAKE_CHROME"

const (
	// ModeServe answers /json/version on --remote-debugging-port (0 picks a
	// free port) and writes the port to DevToolsActivePort in --user-data-dir,
	// like Chrome. When its
	// DevTools pipe (fd 3) closes, it writes FlushedFile in --user-data-dir
	// and exits 0, like Chrome flushing its profile.
	ModeServe = "serve"
	// ModeFail writes "boom" to stderr and exits with status 1.
	ModeFail = "fail"
)

// FlushedFile is the file that ModeServe writes in --user-data-dir on a clean exit.
const FlushedFile = "flushed"

// Main makes the process a fake Chrome when EnvMode is set; it then never
// returns. Call it first in TestMain.
func Main() {
	switch os.Getenv(EnvMode) {
	case "":
		return
	case ModeFail:
		fmt.Fprintln(os.Stderr, "boom")
		os.Exit(1)
	}
	port, profile := "", ""
	for _, a := range os.Args[1:] {
		if v, ok := strings.CutPrefix(a, "--remote-debugging-port="); ok {
			port = v
		}
		if v, ok := strings.CutPrefix(a, "--user-data-dir="); ok {
			profile = v
		}
	}
	go func() {
		_, _ = io.Copy(io.Discard, os.NewFile(3, "devtools-pipe"))
		if err := os.MkdirAll(profile, 0o700); err == nil {
			_ = os.WriteFile(filepath.Join(profile, FlushedFile), nil, 0o600)
		}
		os.Exit(0)
	}()
	ln, err := net.Listen("tcp", "127.0.0.1:"+port)
	if err == nil {
		err = os.MkdirAll(profile, 0o700)
	}
	if err == nil {
		active := fmt.Sprintf("%d\n/devtools/browser/fake\n", ln.Addr().(*net.TCPAddr).Port)
		err = os.WriteFile(filepath.Join(profile, "DevToolsActivePort"), []byte(active), 0o600)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "fake chrome:", err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, "fake chrome listening on", ln.Addr())
	mux := http.NewServeMux()
	mux.HandleFunc("/json/version", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = fmt.Fprintf(w, `{"Browser":"FakeChrome/1.0","Pid":%d}`, os.Getpid())
	})
	_ = http.Serve(ln, mux)
	os.Exit(1)
}

// Binary returns the path of the running test binary.
func Binary(t testing.TB) string {
	t.Helper()
	p, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	return p
}
