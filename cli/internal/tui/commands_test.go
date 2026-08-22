package tui

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/skills"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func TestSkillPrompt(t *testing.T) {
	s := skills.Skill{Name: "release-notes", Body: "Do the thing."}

	withArg := skillPrompt(s, "for v2")
	if !strings.Contains(withArg, `<skill name="release-notes">`) {
		t.Errorf("missing skill tag: %q", withArg)
	}
	if !strings.Contains(withArg, "Do the thing.") {
		t.Errorf("missing skill body: %q", withArg)
	}
	if !strings.Contains(withArg, "My request: for v2") {
		t.Errorf("missing user request: %q", withArg)
	}

	noArg := skillPrompt(s, "")
	if !strings.Contains(noArg, "My request: run this skill.") {
		t.Errorf("missing default request: %q", noArg)
	}
}

func TestIsBuiltinCommand(t *testing.T) {
	for _, cmd := range []string{"/help", "/skills", "/new", "/resume", "/quit"} {
		if !isBuiltinCommand(cmd) {
			t.Errorf("isBuiltinCommand(%q) = false, want true", cmd)
		}
	}
	if isBuiltinCommand("/release-notes") {
		t.Error("isBuiltinCommand(/release-notes) = true, want false")
	}
}

func TestRenderHelpIncludesSkills(t *testing.T) {
	help := renderHelp([]skills.Skill{{Name: "foo", Description: "Foo skill."}})
	if !strings.Contains(help, "/foo") || !strings.Contains(help, "Foo skill.") {
		t.Errorf("help missing skill entry: %q", help)
	}

	bare := renderHelp(nil)
	if strings.Contains(bare, "Skills\n") {
		t.Errorf("help without skills should omit the Skills section: %q", bare)
	}
}

// TestSkillInvocationSendsPrompt verifies the full invocation path: the
// agent receives the skill body plus the user's request, while the chat
// view shows only the compact command line.
func TestSkillInvocationSendsPrompt(t *testing.T) {
	bodyCh := make(chan string, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/chat/send-chat-message" {
			w.WriteHeader(http.StatusOK)
			return
		}
		raw, _ := io.ReadAll(r.Body)
		bodyCh <- string(raw)
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	m := NewModel(config.OnyxCliConfig{ServerURL: srv.URL}, testutil.NewClient(srv.URL))
	m.skills = []skills.Skill{{
		Name:        "release-notes",
		Description: "Draft release notes.",
		Body:        "Collect changes and draft release notes.",
	}}

	updated, cmd := handleSlashCommand(m, "/release-notes for v2.1")
	if cmd == nil {
		t.Fatal("expected a stream command, got nil")
	}

	var sent string
	select {
	case sent = <-bodyCh:
	case <-time.After(5 * time.Second):
		t.Fatal("agent never received the chat message")
	}

	var payload struct {
		Message string `json:"message"`
	}
	if err := json.Unmarshal([]byte(sent), &payload); err != nil {
		t.Fatalf("bad payload: %v", err)
	}
	if !strings.Contains(payload.Message, `<skill name="release-notes">`) ||
		!strings.Contains(payload.Message, "Collect changes and draft release notes.") ||
		!strings.Contains(payload.Message, "My request: for v2.1") {
		t.Errorf("sent message missing skill content: %q", payload.Message)
	}

	var userEntry string
	for _, e := range updated.viewport.entries {
		if e.kind == entryUser {
			userEntry = e.content
		}
	}
	if userEntry != "/release-notes for v2.1" {
		t.Errorf("chat view shows %q, want compact command line", userEntry)
	}
}

func TestSkillPromptArgumentsPlaceholder(t *testing.T) {
	s := skills.Skill{Name: "greet", Body: "Say hello to $ARGUMENTS politely."}

	got := skillPrompt(s, "Alice")
	if !strings.Contains(got, "Say hello to Alice politely.") {
		t.Errorf("$ARGUMENTS not substituted: %q", got)
	}
	if strings.Contains(got, "My request:") {
		t.Errorf("request line should be omitted when $ARGUMENTS is used: %q", got)
	}
}

func TestSkillMenuCompletion(t *testing.T) {
	m := newInputModel()
	m.setSkillCommands([]slashCommand{{command: "/release-notes", description: "Draft notes"}})
	m.textInput.SetValue("/rel")
	m = m.updateMenu()

	if !m.menuVisible || len(m.menuItems) != 1 || m.menuItems[0].command != "/release-notes" {
		t.Errorf("menu = visible:%v items:%+v", m.menuVisible, m.menuItems)
	}
}
