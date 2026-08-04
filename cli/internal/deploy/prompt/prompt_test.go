package prompt

import (
	"bytes"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

// interactiveIOS builds an IOStreams that reads input and claims to be a TTY.
func interactiveIOS(input string) (*iostreams.IOStreams, *bytes.Buffer) {
	out := &bytes.Buffer{}
	return &iostreams.IOStreams{
		In:          strings.NewReader(input),
		Out:         out,
		ErrOut:      &bytes.Buffer{},
		IsStdinTTY:  true,
		IsStdoutTTY: true,
	}, out
}

func TestAskReturnsInput(t *testing.T) {
	ios, out := interactiveIOS("v1.2.3\n")
	p := New(ios, false)
	got, err := p.Ask("Enter tag: ", "edge")
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}
	if got != "v1.2.3" {
		t.Fatalf("got %q", got)
	}
	if !strings.Contains(out.String(), "Enter tag: ") {
		t.Fatalf("prompt not printed: %q", out.String())
	}
}

func TestAskEmptyInputUsesDefault(t *testing.T) {
	ios, _ := interactiveIOS("\n")
	got, err := New(ios, false).Ask("tag? ", "edge")
	if err != nil || got != "edge" {
		t.Fatalf("got %q, %v", got, err)
	}
}

func TestAskNonInteractiveUsesDefaultWithoutReading(t *testing.T) {
	ios, out := interactiveIOS("should-not-be-read\n")
	ios.IsStdinTTY = false
	got, err := New(ios, false).Ask("tag? ", "edge")
	if err != nil || got != "edge" {
		t.Fatalf("got %q, %v", got, err)
	}
	if out.Len() != 0 {
		t.Fatalf("prompt printed in non-interactive mode: %q", out.String())
	}
}

func TestAskAssumeDefaultsFlag(t *testing.T) {
	ios, _ := interactiveIOS("typed\n")
	got, err := New(ios, true).Ask("tag? ", "edge")
	if err != nil || got != "edge" {
		t.Fatalf("got %q, %v", got, err)
	}
}

func TestConfirm(t *testing.T) {
	cases := []struct {
		input      string
		defaultYes bool
		want       bool
	}{
		{"y\n", false, true},
		{"Y\n", false, true},
		{"yes\n", false, true},
		{"n\n", true, false},
		{"No\n", true, false},
		{"\n", true, true},
		{"\n", false, false},
		{"junk\n", true, false},
	}
	for _, c := range cases {
		ios, _ := interactiveIOS(c.input)
		got, err := New(ios, false).Confirm("continue? ", c.defaultYes)
		if err != nil {
			t.Fatalf("Confirm(%q): %v", c.input, err)
		}
		if got != c.want {
			t.Errorf("Confirm(%q, default=%v) = %v, want %v", c.input, c.defaultYes, got, c.want)
		}
	}
}

func TestConfirmTyped(t *testing.T) {
	ios, _ := interactiveIOS("DELETE\n")
	ok, err := New(ios, false).ConfirmTyped("type DELETE: ", "DELETE")
	if err != nil || !ok {
		t.Fatalf("got %v, %v", ok, err)
	}

	ios, _ = interactiveIOS("delete\n")
	ok, err = New(ios, false).ConfirmTyped("type DELETE: ", "DELETE")
	if err != nil || ok {
		t.Fatalf("case-insensitive match must fail: %v, %v", ok, err)
	}

	// Never satisfied non-interactively.
	ios, _ = interactiveIOS("DELETE\n")
	ios.IsStdinTTY = false
	ok, err = New(ios, false).ConfirmTyped("type DELETE: ", "DELETE")
	if err != nil || ok {
		t.Fatalf("non-interactive must refuse: %v, %v", ok, err)
	}
}

func TestSequentialPromptsShareReader(t *testing.T) {
	ios, _ := interactiveIOS("first\nsecond\n")
	p := New(ios, false)
	a, _ := p.Ask("a? ", "")
	b, _ := p.Ask("b? ", "")
	if a != "first" || b != "second" {
		t.Fatalf("got %q, %q", a, b)
	}
}

func TestEOFReadsAsEmpty(t *testing.T) {
	ios, _ := interactiveIOS("") // immediate EOF
	got, err := New(ios, false).Ask("tag? ", "edge")
	if err != nil || got != "edge" {
		t.Fatalf("got %q, %v", got, err)
	}
}
