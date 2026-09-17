// Package prompt provides the line-based interactive prompts the deploy
// commands use. Everything routes through IOStreams (no direct os.Stdin, no
// TUI dependencies) so tests drive prompts with buffers and non-interactive
// runs fall back to defaults.
package prompt

import (
	"bufio"
	"fmt"
	"io"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

// Prompter asks questions on ios.Out and reads answers from ios.In. When
// AssumeDefaults is set (--no-prompt, or no TTY), every prompt resolves to
// its default without reading input — mirroring install.sh's behavior.
type Prompter struct {
	ios            *iostreams.IOStreams
	reader         *bufio.Reader
	AssumeDefaults bool
}

func New(ios *iostreams.IOStreams, assumeDefaults bool) *Prompter {
	return &Prompter{
		ios:            ios,
		reader:         bufio.NewReader(ios.In),
		AssumeDefaults: assumeDefaults || !ios.IsInteractive(),
	}
}

// Ask prints question and returns the entered line, or defaultVal on empty
// input / non-interactive runs.
func (p *Prompter) Ask(question, defaultVal string) (string, error) {
	if p.AssumeDefaults {
		return defaultVal, nil
	}
	fmt.Fprint(p.ios.Out, question)
	line, err := p.readLine()
	if err != nil {
		return "", err
	}
	if line == "" {
		return defaultVal, nil
	}
	return line, nil
}

// Confirm asks a Y/n (or y/N) question.
func (p *Prompter) Confirm(question string, defaultYes bool) (bool, error) {
	def := "n"
	if defaultYes {
		def = "y"
	}
	answer, err := p.Ask(question, def)
	if err != nil {
		return false, err
	}
	answer = strings.ToLower(strings.TrimSpace(answer))
	if answer == "" {
		return defaultYes, nil
	}
	return strings.HasPrefix(answer, "y"), nil
}

// ConfirmTyped requires the exact requiredText to be typed (used for
// destructive actions, e.g. uninstall's DELETE). Never satisfied by default:
// non-interactive callers must pass an explicit flag instead.
func (p *Prompter) ConfirmTyped(question, requiredText string) (bool, error) {
	if p.AssumeDefaults {
		return false, nil
	}
	fmt.Fprint(p.ios.Out, question)
	line, err := p.readLine()
	if err != nil {
		return false, err
	}
	return line == requiredText, nil
}

// AcknowledgeEnter waits for Enter (the "press Enter to continue" pattern);
// a no-op when non-interactive.
func (p *Prompter) AcknowledgeEnter(message string) error {
	if p.AssumeDefaults {
		return nil
	}
	fmt.Fprint(p.ios.Out, message)
	_, err := p.readLine()
	return err
}

func (p *Prompter) readLine() (string, error) {
	line, err := p.reader.ReadString('\n')
	if err != nil && err != io.EOF {
		return "", err
	}
	// EOF with partial input is fine; EOF with nothing reads as empty.
	return strings.TrimSpace(line), nil
}
