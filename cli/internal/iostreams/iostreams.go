package iostreams

import (
	"io"
	"os"

	"golang.org/x/term"
)

// IOStreams bundles the standard I/O streams for a CLI invocation.
type IOStreams struct {
	In          io.Reader
	Out         io.Writer
	ErrOut      io.Writer
	IsStdinTTY  bool
	IsStdoutTTY bool
	IsStderrTTY bool
}

// System returns an IOStreams wired to the real os.Stdin/Stdout/Stderr.
func System() *IOStreams {
	return &IOStreams{
		In:          os.Stdin,
		Out:         os.Stdout,
		ErrOut:      os.Stderr,
		IsStdinTTY:  term.IsTerminal(int(os.Stdin.Fd())),
		IsStdoutTTY: term.IsTerminal(int(os.Stdout.Fd())),
		IsStderrTTY: term.IsTerminal(int(os.Stderr.Fd())),
	}
}

// IsInteractive returns true when both stdin and stdout are terminals.
func (s *IOStreams) IsInteractive() bool {
	return s.IsStdinTTY && s.IsStdoutTTY
}
