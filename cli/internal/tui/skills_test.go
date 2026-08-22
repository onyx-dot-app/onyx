package tui

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// stubClient records the message passed to SendMessageStream.
type stubClient struct {
	api.ClientAPI
	sent []string
}

func (c *stubClient) SendMessageStream(
	ctx context.Context,
	message string,
	chatSessionID *string,
	agentID int,
	parentMessageID *int,
	fileDescriptors []models.FileDescriptorPayload,
) <-chan models.StreamEvent {
	c.sent = append(c.sent, message)
	ch := make(chan models.StreamEvent)
	close(ch)
	return ch
}

// newSkillsModel builds a Model whose skills come from a temporary project
// directory, with an empty home directory so real skills cannot leak in.
func newSkillsModel(t *testing.T, files map[string]string) (Model, *stubClient) {
	t.Helper()

	project := t.TempDir()
	for name, content := range files {
		dir := filepath.Join(project, ".agents", "skills", name)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatalf("MkdirAll: %v", err)
		}
		if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte(content), 0o644); err != nil {
			t.Fatalf("WriteFile: %v", err)
		}
	}

	t.Chdir(project)
	t.Setenv("HOME", t.TempDir())

	client := &stubClient{}
	return NewModel(config.OnyxCliConfig{ServerURL: "http://localhost"}, client), client
}

func TestSkillCommandSendsExpandedPrompt(t *testing.T) {
	m, client := newSkillsModel(t, map[string]string{
		"triage": "---\nname: triage\ndescription: Triage an incident.\n---\n\nTriage: $ARGUMENTS\n",
	})

	if _, ok := m.skills["triage"]; !ok {
		t.Fatalf("triage skill not discovered, got %v", m.skills)
	}

	m, _ = handleSlashCommand(m, "/triage payments API 500s")

	if len(client.sent) != 1 {
		t.Fatalf("sent %d messages, want 1", len(client.sent))
	}
	if client.sent[0] != "Triage: payments API 500s" {
		t.Errorf("sent %q, want the expanded prompt", client.sent[0])
	}
	if !m.isStreaming {
		t.Error("expected the model to be streaming after running a skill")
	}
}

func TestSkillCommandWithoutArguments(t *testing.T) {
	m, client := newSkillsModel(t, map[string]string{
		"standup": "Summarize yesterday's standup.\n",
	})

	_, _ = handleSlashCommand(m, "/standup")

	if len(client.sent) != 1 || client.sent[0] != "Summarize yesterday's standup." {
		t.Fatalf("sent %v, want the skill body", client.sent)
	}
}

func TestSkillCommandIsCaseInsensitive(t *testing.T) {
	m, client := newSkillsModel(t, map[string]string{
		"standup": "Summarize yesterday's standup.\n",
	})

	_, _ = handleSlashCommand(m, "/StandUp")

	if len(client.sent) != 1 {
		t.Fatalf("sent %d messages, want 1", len(client.sent))
	}
}

// A body of only $ARGUMENTS expands to nothing, which must not be sent.
func TestSkillWithEmptyExpansionIsNotSent(t *testing.T) {
	m, client := newSkillsModel(t, map[string]string{
		"echo": "$ARGUMENTS\n",
	})

	m, _ = handleSlashCommand(m, "/echo")

	if len(client.sent) != 0 {
		t.Fatalf("sent %v, want nothing", client.sent)
	}
	if m.isStreaming {
		t.Error("expected no stream for an empty expansion")
	}
	last := m.viewport.entries[len(m.viewport.entries)-1]
	if !strings.Contains(stripANSI(last.rendered), "needs arguments") {
		t.Errorf("expected an arguments warning, got %q", stripANSI(last.rendered))
	}
}

func TestSkillCannotOverrideBuiltinCommand(t *testing.T) {
	m, client := newSkillsModel(t, map[string]string{
		"help": "This skill must never run.\n",
	})

	if _, ok := m.skills["help"]; ok {
		t.Error("a skill named help should be dropped, not registered")
	}

	m, _ = handleSlashCommand(m, "/help")

	if len(client.sent) != 0 {
		t.Fatalf("sent %v, want the built-in /help to win", client.sent)
	}
	last := m.viewport.entries[len(m.viewport.entries)-1]
	if !strings.Contains(stripANSI(last.rendered), "Onyx CLI Commands") {
		t.Errorf("expected built-in help output, got %q", stripANSI(last.rendered))
	}
}

func TestUnknownCommandStillWarns(t *testing.T) {
	m, client := newSkillsModel(t, nil)

	m, _ = handleSlashCommand(m, "/nope")

	if len(client.sent) != 0 {
		t.Fatalf("sent %v, want nothing", client.sent)
	}
	last := m.viewport.entries[len(m.viewport.entries)-1]
	if !strings.Contains(stripANSI(last.rendered), "Unknown command") {
		t.Errorf("expected an unknown command warning, got %q", stripANSI(last.rendered))
	}
}

func TestSkillIsRefusedWhileStreaming(t *testing.T) {
	m, client := newSkillsModel(t, map[string]string{
		"standup": "Summarize yesterday's standup.\n",
	})
	m.isStreaming = true

	m, _ = handleSlashCommand(m, "/standup")

	if len(client.sent) != 0 {
		t.Fatalf("sent %v while streaming, want nothing", client.sent)
	}
	last := m.viewport.entries[len(m.viewport.entries)-1]
	if !strings.Contains(stripANSI(last.rendered), "Wait for the current response") {
		t.Errorf("expected a wait warning, got %q", stripANSI(last.rendered))
	}
}

func TestSkillsAppearInCommandMenu(t *testing.T) {
	m, _ := newSkillsModel(t, map[string]string{
		"triage": "---\nname: triage\ndescription: Triage an incident.\n---\n\nTriage it.\n",
	})

	m.input.textInput.SetValue("/tri")
	m.input = m.input.updateMenu()

	if !m.input.menuVisible || len(m.input.menuItems) != 1 {
		t.Fatalf("menu items = %+v, want the triage skill", m.input.menuItems)
	}
	item := m.input.menuItems[0]
	if item.command != "/triage" {
		t.Errorf("command = %q, want /triage", item.command)
	}
	if item.description != "Triage an incident." {
		t.Errorf("description = %q", item.description)
	}
	if !item.optionalArg {
		t.Error("skill commands should prefill with a trailing space on Tab")
	}
}

func TestSkillMenuEnterRunsTheSkill(t *testing.T) {
	m, _ := newSkillsModel(t, map[string]string{
		"triage": "Triage it.\n",
	})

	m.input.textInput.SetValue("/tri")
	m.input = m.input.updateMenu()

	in, cmd := m.input.handleKey(tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd == nil {
		t.Fatal("expected a command from Enter on a skill menu item")
	}
	if in.menuVisible {
		t.Error("menu should close after Enter")
	}
	msg, ok := cmd().(submitMsg)
	if !ok {
		t.Fatalf("got %T, want submitMsg", cmd())
	}
	if msg.text != "/triage" {
		t.Errorf("submitted %q, want /triage", msg.text)
	}
}

func TestSkillsCommandListsSkills(t *testing.T) {
	m, _ := newSkillsModel(t, map[string]string{
		"triage": "---\nname: triage\ndescription: Triage an incident.\n---\n\nTriage it.\n",
	})

	m, _ = cmdSkills(m)

	last := stripANSI(m.viewport.entries[len(m.viewport.entries)-1].rendered)
	if !strings.Contains(last, "/triage") || !strings.Contains(last, "Triage an incident.") {
		t.Errorf("listing = %q, want the triage skill", last)
	}
}

func TestSkillsCommandReloadsFromDisk(t *testing.T) {
	m, _ := newSkillsModel(t, nil)

	if len(m.skills) != 0 {
		t.Fatalf("skills = %v, want none", m.skills)
	}

	dir := filepath.Join(".agents", "skills", "late")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte("Added later.\n"), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	m, _ = cmdSkills(m)

	if _, ok := m.skills["late"]; !ok {
		t.Errorf("skills = %v, want the newly added skill", m.skills)
	}
}
