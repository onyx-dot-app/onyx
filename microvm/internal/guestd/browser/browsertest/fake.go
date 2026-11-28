// Package browsertest turns a test binary into a fake Chrome or a fake
// browser service for tests of the browser package and its callers. It also
// has the service framing for tests.
package browsertest

import (
	"encoding/binary"
	"encoding/json"
	"errors"
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

// ServiceScript is the browser.Config.ServiceScript that makes the test
// binary (as browser.Config.Node) a fake browser service.
const ServiceScript = "fake-browser-service"

// EnvServiceMode selects the fake service: empty serves, ServiceFail fails.
const EnvServiceMode = "GUESTD_FAKE_SERVICE"

// ServiceFail writes "service boom" to stderr and exits with status 1.
const ServiceFail = "fail"

// Main makes the process a fake Chrome when EnvMode is set, or a fake
// service when its first argument is ServiceScript; it then never returns.
// Call it first in TestMain.
func Main() {
	if len(os.Args) > 1 && os.Args[1] == ServiceScript {
		serviceMain()
	}
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

// serviceMain is the fake service. It listens on ONYX_BROWSER_SOCKET and
// answers each call with {"ok":true,"result":{...}}: the call's method,
// its CDP URL, sessions root and pid.
func serviceMain() {
	if os.Getenv(EnvServiceMode) == ServiceFail {
		fmt.Fprintln(os.Stderr, "service boom")
		os.Exit(1)
	}
	cdp := os.Getenv("ONYX_BROWSER_CDP_URL")
	ln, err := net.Listen("unix", os.Getenv("ONYX_BROWSER_SOCKET"))
	if err != nil {
		fmt.Fprintln(os.Stderr, "fake service:", err)
		os.Exit(1)
	}
	for {
		conn, err := ln.Accept()
		if err != nil {
			os.Exit(1)
		}
		go func() {
			defer func() { _ = conn.Close() }()
			var call struct {
				Method string `json:"method"`
			}
			if err := ReadJSON(conn, &call); err != nil {
				return
			}
			_ = WriteJSON(conn, map[string]any{"ok": true, "result": map[string]any{
				"method": call.Method, "cdpUrl": cdp, "sessionsRoot": os.Getenv("ONYX_SESSIONS_ROOT"), "pid": os.Getpid(),
			}})
		}()
	}
}

// kindJSON is the kind byte of a JSON frame of the service framing.
const kindJSON = 1

const maxFrame = 16 << 20

// WriteJSON writes v as one JSON frame: a 4-byte big-endian length of the
// rest, the kind byte, then the payload.
func WriteJSON(w io.Writer, v any) error {
	payload, err := json.Marshal(v)
	if err != nil {
		return err
	}
	buf := make([]byte, 5+len(payload))
	binary.BigEndian.PutUint32(buf, uint32(1+len(payload)))
	buf[4] = kindJSON
	copy(buf[5:], payload)
	_, err = w.Write(buf)
	return err
}

// ReadJSON reads one frame, which must be JSON, into v.
func ReadJSON(r io.Reader, v any) error {
	var head [5]byte
	if _, err := io.ReadFull(r, head[:]); err != nil {
		return err
	}
	n := binary.BigEndian.Uint32(head[:4])
	if n == 0 || n > maxFrame {
		return fmt.Errorf("bad frame length %d", n)
	}
	payload := make([]byte, n-1)
	if _, err := io.ReadFull(r, payload); err != nil {
		return err
	}
	if head[4] != kindJSON {
		return errors.New("not a JSON frame")
	}
	return json.Unmarshal(payload, v)
}
