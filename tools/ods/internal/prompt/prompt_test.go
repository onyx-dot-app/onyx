package prompt

import (
	"bufio"
	"errors"
	"io"
	"strings"
	"testing"
)

func input(s string) *bufio.Reader {
	return bufio.NewReader(strings.NewReader(s))
}

func TestReadString_repromptsUntilAValueIsGiven(t *testing.T) {
	var out strings.Builder

	got, err := readString(input("\n   \n  onyx  \n"), &out, "Name: ")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "onyx" {
		t.Fatalf("expected %q, got %q", "onyx", got)
	}
	if n := strings.Count(out.String(), "Name: "); n != 3 {
		t.Errorf("expected the prompt 3 times, got %d in %q", n, out.String())
	}
	if n := strings.Count(out.String(), "Value cannot be empty."); n != 2 {
		t.Errorf("expected 2 empty-value warnings, got %d in %q", n, out.String())
	}
}

func TestReadString_returnsTheErrorWhenInputEnds(t *testing.T) {
	// A final line without a newline is not accepted: the input ended first.
	_, err := readString(input("\npartial"), io.Discard, "Name: ")
	if !errors.Is(err, io.EOF) {
		t.Fatalf("expected io.EOF, got %v", err)
	}
}

func TestReadChoice(t *testing.T) {
	options := []string{"alpha", "beta", "gamma"}
	tests := []struct {
		name         string
		input        string
		defaultIndex int
		want         int
		wantRetries  int
	}{
		{name: "number picks the option", input: "3\n", want: 2},
		{name: "empty input picks the default", input: "\n", defaultIndex: 1, want: 1},
		{name: "surrounding spaces are ignored", input: "  1 \n", defaultIndex: 2, want: 0},
		{name: "out of range and non-numbers re-prompt", input: "0\n4\nbeta\n2\n", want: 1, wantRetries: 3},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var out strings.Builder

			got, err := readChoice(input(tt.input), &out, "Pick one", options, tt.defaultIndex)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.want {
				t.Fatalf("expected %d, got %d", tt.want, got)
			}
			if n := strings.Count(out.String(), "Please enter a number between 1 and 3\n"); n != tt.wantRetries {
				t.Errorf("expected %d retry messages, got %d in %q", tt.wantRetries, n, out.String())
			}
		})
	}
}

func TestReadChoice_listsTheOptionsAndTheDefault(t *testing.T) {
	var out strings.Builder

	if _, err := readChoice(input("\n"), &out, "Pick one", []string{"alpha", "beta"}, 1); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	want := "Pick one\n  1) alpha\n  2) beta\nChoose 1-2 [2]: "
	if out.String() != want {
		t.Fatalf("expected %q, got %q", want, out.String())
	}
}

func TestReadChoice_returnsTheErrorWhenInputEnds(t *testing.T) {
	_, err := readChoice(input("9\n"), io.Discard, "Pick one", []string{"alpha"}, 0)
	if !errors.Is(err, io.EOF) {
		t.Fatalf("expected io.EOF, got %v", err)
	}
}

func TestSelectIndex_withoutATerminalUsesTheNumberedPrompt(t *testing.T) {
	var out strings.Builder

	got, ok, err := selectIndex(input("2\n"), &out, false, "Pick one", []string{"alpha", "beta"}, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 1 || !ok {
		t.Fatalf("expected (1, true), got (%d, %t)", got, ok)
	}
	if !strings.Contains(out.String(), "  2) beta\n") {
		t.Errorf("expected the numbered list on the output, got %q", out.String())
	}

	// The numbered prompt cannot cancel, so running out of input is an error.
	if _, _, err := selectIndex(input(""), io.Discard, false, "Pick one", []string{"alpha"}, 0); !errors.Is(err, io.EOF) {
		t.Fatalf("expected io.EOF, got %v", err)
	}
}

func TestReadConfirm(t *testing.T) {
	tests := []struct {
		name        string
		input       string
		want        bool
		wantRetries int
	}{
		{name: "empty input means yes", input: "\n", want: true},
		{name: "y", input: "y\n", want: true},
		{name: "YES in capitals", input: " YES \n", want: true},
		{name: "n", input: "n\n", want: false},
		{name: "No in mixed case", input: "No\n", want: false},
		{name: "other answers re-prompt", input: "maybe\nnope\nn\n", want: false, wantRetries: 2},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var out strings.Builder

			got, err := readConfirm(input(tt.input), &out, "Continue? ")
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.want {
				t.Fatalf("expected %t, got %t", tt.want, got)
			}
			if n := strings.Count(out.String(), "Please enter 'yes' or 'no'\n"); n != tt.wantRetries {
				t.Errorf("expected %d retry messages, got %d in %q", tt.wantRetries, n, out.String())
			}
		})
	}
}

func TestReadConfirm_returnsTheErrorWhenInputEnds(t *testing.T) {
	_, err := readConfirm(input("maybe\n"), io.Discard, "Continue? ")
	if !errors.Is(err, io.EOF) {
		t.Fatalf("expected io.EOF, got %v", err)
	}
}
