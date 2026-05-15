package cmd

import (
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

func iosWithStdin(content string) *iostreams.IOStreams {
	return &iostreams.IOStreams{
		In:         strings.NewReader(content),
		Out:        io.Discard,
		ErrOut:     io.Discard,
		IsStdinTTY: false, // simulate piped input
	}
}

func iosTTY() *iostreams.IOStreams {
	return &iostreams.IOStreams{
		In:         strings.NewReader(""),
		Out:        io.Discard,
		ErrOut:     io.Discard,
		IsStdinTTY: true, // terminal, no piped data
	}
}

func TestResolveQuestion(t *testing.T) {
	tests := []struct {
		name    string
		ios     *iostreams.IOStreams
		args    []string
		prompt  string
		want    string
		wantErr bool
	}{
		{
			name: "positional_arg_only",
			ios:  iosTTY(),
			args: []string{"What is Onyx?"},
			want: "What is Onyx?",
		},
		{
			name:   "prompt_only",
			ios:    iosTTY(),
			prompt: "Summarize this",
			want:   "Summarize this",
		},
		{
			name: "stdin_only",
			ios:  iosWithStdin("piped content"),
			want: "piped content",
		},
		{
			name: "arg_plus_stdin",
			ios:  iosWithStdin("error log data"),
			args: []string{"Find the root cause"},
			want: "Find the root cause\n\nerror log data",
		},
		{
			name:   "prompt_plus_stdin",
			ios:    iosWithStdin("error log data"),
			prompt: "Find the root cause",
			want:   "Find the root cause\n\nerror log data",
		},
		{
			name:    "arg_and_prompt_error",
			ios:     iosTTY(),
			args:    []string{"arg question"},
			prompt:  "prompt question",
			wantErr: true,
		},
		{
			name:    "nothing_provided",
			ios:     iosTTY(),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := resolveQuestion(tt.ios, tt.args, tt.prompt)
			if tt.wantErr {
				if err == nil {
					t.Fatal("want error, got nil")
				}
				var exitErr *exitcodes.ExitError
				if !errors.As(err, &exitErr) {
					t.Fatalf("want *ExitError, got %T: %v", err, err)
				}
				if exitErr.Code != exitcodes.BadRequest {
					t.Errorf("exit code = %d, want %d", exitErr.Code, exitcodes.BadRequest)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.want {
				t.Errorf("got %q, want %q", got, tt.want)
			}
		})
	}
}
