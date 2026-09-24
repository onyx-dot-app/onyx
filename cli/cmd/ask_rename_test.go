package cmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

const testSessionID = "11111111-2222-3333-4444-555555555555"

// lockedBuffer lets the fake server read the answer written so far without
// racing the command goroutine.
type lockedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *lockedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *lockedBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// renameRecord is what the fake rename endpoint saw, captured under lock.
type renameRecord struct {
	mu            sync.Mutex
	calls         int
	payload       map[string]any
	outputAtCall  string
	renameStatus  int
	streamPackets []string
}

func streamLine(objType string, extra map[string]any) string {
	obj := map[string]any{"type": objType}
	for k, v := range extra {
		obj[k] = v
	}
	line, _ := json.Marshal(map[string]any{
		"identity": map[string]any{"response_id": 1, "message_id": "answer", "part_id": "text"},
		"obj":      obj,
	})
	return string(line)
}

// newAskServer serves one streamed answer and records the rename request.
func newAskServer(t *testing.T, rec *renameRecord, out *lockedBuffer) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
		for _, p := range rec.streamPackets {
			fmt.Fprintln(w, p)
		}
	})
	mux.HandleFunc("/api/chat/rename-chat-session", func(w http.ResponseWriter, r *http.Request) {
		rec.mu.Lock()
		defer rec.mu.Unlock()
		rec.calls++
		rec.outputAtCall = out.String()
		_ = json.NewDecoder(r.Body).Decode(&rec.payload)
		w.WriteHeader(rec.renameStatus)
		fmt.Fprint(w, `{"new_name":"Generated Title"}`)
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	testutil.IsolateConfig(t, srv.URL)
	return srv
}

func runAsk(t *testing.T, args ...string) (*lockedBuffer, *bytes.Buffer, *renameRecord, error) {
	t.Helper()
	out := &lockedBuffer{}
	errOut := &bytes.Buffer{}
	rec := &renameRecord{
		renameStatus: http.StatusOK,
		streamPackets: []string{
			streamLine("item_update", map[string]any{"item": map[string]any{"kind": "text", "purpose": "answer", "text": "hello ", "status": "running"}}),
			streamLine("item_delta", map[string]any{"delta": map[string]any{"kind": "text", "text": "world"}}),
			streamLine("stop", nil),
		},
	}
	newAskServer(t, rec, out)
	ios := &iostreams.IOStreams{In: &bytes.Buffer{}, Out: out, ErrOut: errOut, IsStdinTTY: true, IsStdoutTTY: true}
	cmd := newAskCmd(ios)
	cmd.SetArgs(append([]string{"question"}, args...))
	err := cmd.Execute()
	return out, errOut, rec, err
}

func TestAsk_NamesSessionAfterAnswerIsPrinted(t *testing.T) {
	out, errOut, rec, err := runAsk(t)
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := out.String(); !strings.Contains(got, "hello world") {
		t.Fatalf("answer not printed, got %q", got)
	}
	if rec.calls != 1 {
		t.Fatalf("rename calls = %d, want 1", rec.calls)
	}
	if !strings.Contains(rec.outputAtCall, "hello world") {
		t.Errorf("rename requested before the answer was flushed, output then = %q", rec.outputAtCall)
	}
	if rec.payload["chat_session_id"] != testSessionID {
		t.Errorf("chat_session_id = %v, want %s", rec.payload["chat_session_id"], testSessionID)
	}
	if _, hasName := rec.payload["name"]; hasName {
		t.Errorf("rename sent a name, want the backend to generate one: %v", rec.payload)
	}
	if errOut.Len() != 0 {
		t.Errorf("unexpected stderr: %q", errOut.String())
	}
}

func TestAsk_JSONModeNamesSession(t *testing.T) {
	out, _, rec, err := runAsk(t, "--json")
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if !strings.Contains(out.String(), `"type":"stop"`) {
		t.Fatalf("stop event not emitted, got %q", out.String())
	}
	if rec.calls != 1 {
		t.Errorf("rename calls = %d, want 1", rec.calls)
	}
}

func TestAsk_QuietModeNamesSession(t *testing.T) {
	out, _, rec, err := runAsk(t, "--quiet")
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if !strings.Contains(out.String(), "hello world") {
		t.Fatalf("answer not printed, got %q", out.String())
	}
	if rec.calls != 1 {
		t.Errorf("rename calls = %d, want 1", rec.calls)
	}
}

func TestAsk_RenameFailureWarnsAndKeepsExitZero(t *testing.T) {
	out := &lockedBuffer{}
	errOut := &bytes.Buffer{}
	rec := &renameRecord{
		renameStatus:  http.StatusInternalServerError,
		streamPackets: []string{streamLine("item_update", map[string]any{"item": map[string]any{"kind": "text", "purpose": "answer", "text": "hi", "status": "complete"}}), streamLine("stop", nil)},
	}
	newAskServer(t, rec, out)
	ios := &iostreams.IOStreams{In: &bytes.Buffer{}, Out: out, ErrOut: errOut, IsStdinTTY: true, IsStdoutTTY: true}
	cmd := newAskCmd(ios)
	cmd.SetArgs([]string{"question"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("rename failure must not fail the command, got %v", err)
	}
	if !strings.Contains(errOut.String(), "could not name chat session") {
		t.Errorf("missing warning on stderr, got %q", errOut.String())
	}
}

func TestAsk_StreamErrorSkipsRename(t *testing.T) {
	out := &lockedBuffer{}
	rec := &renameRecord{
		renameStatus:  http.StatusOK,
		streamPackets: []string{streamLine("error", map[string]any{"exception": "boom"})},
	}
	newAskServer(t, rec, out)
	ios := &iostreams.IOStreams{In: &bytes.Buffer{}, Out: out, ErrOut: &bytes.Buffer{}, IsStdinTTY: true, IsStdoutTTY: true}
	cmd := newAskCmd(ios)
	cmd.SilenceUsage = true
	cmd.SetArgs([]string{"question"})
	if err := cmd.Execute(); err == nil {
		t.Fatal("expected an error from the stream error packet")
	}
	if rec.calls != 0 {
		t.Errorf("rename calls = %d, want 0 after a stream error", rec.calls)
	}
}
