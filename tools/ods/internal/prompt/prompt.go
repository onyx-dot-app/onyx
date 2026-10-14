package prompt

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	"golang.org/x/term"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/tui"
)

// reader is the input reader, can be replaced for testing
var reader = bufio.NewReader(os.Stdin)

// String prompts the user for a free-form line of input. Re-prompts until a
// non-empty value is entered.
func String(prompt string) string {
	response, err := readString(reader, os.Stdout, prompt)
	if err != nil {
		log.Fatalf("Failed to read input: %v", err)
	}
	return response
}

func readString(in *bufio.Reader, out io.Writer, prompt string) (string, error) {
	for {
		_, _ = fmt.Fprint(out, prompt)
		response, err := in.ReadString('\n')
		if err != nil {
			return "", err
		}
		response = strings.TrimSpace(response)
		if response != "" {
			return response, nil
		}
		_, _ = fmt.Fprintln(out, "Value cannot be empty.")
	}
}

// Select asks the user to choose one of options and returns its index. The
// options are shown as an arrow-key list; when the terminal cannot run one
// (piped input, CI, no TTY) it falls back to the numbered Choose prompt. The
// second return is false when the user cancels the list, which the numbered
// fallback cannot do.
func Select(title string, options []string, defaultIndex int) (int, bool) {
	stdinIsTerminal := term.IsTerminal(int(os.Stdin.Fd()))
	index, ok, err := selectIndex(reader, os.Stdout, stdinIsTerminal, title, options, defaultIndex)
	if err != nil {
		log.Fatalf("Failed to read input: %v", err)
	}
	return index, ok
}

func selectIndex(
	in *bufio.Reader,
	out io.Writer,
	stdinIsTerminal bool,
	title string,
	options []string,
	defaultIndex int,
) (int, bool, error) {
	// tcell reads keys from /dev/tty, not stdin, so a list started next to a
	// piped stdin would wait for the terminal and never see the piped answer.
	// The numbered prompt reads the same stdin as every other prompt here.
	if !stdinIsTerminal {
		index, err := readChoice(in, out, title, options, defaultIndex)
		return index, true, err
	}

	index, err := tui.Select(title, options, defaultIndex)
	if err != nil {
		log.Debugf("Arrow-key select unavailable: %v", err)
		index, err := readChoice(in, out, title, options, defaultIndex)
		return index, true, err
	}
	if index < 0 {
		return 0, false, nil
	}
	return index, true, nil
}

// Choose prompts the user with a numbered list of options and returns the
// index of the chosen one. Empty input selects defaultIndex. It re-prompts
// until the input names an option.
func Choose(header string, options []string, defaultIndex int) int {
	index, err := readChoice(reader, os.Stdout, header, options, defaultIndex)
	if err != nil {
		log.Fatalf("Failed to read input: %v", err)
	}
	return index
}

func readChoice(in *bufio.Reader, out io.Writer, header string, options []string, defaultIndex int) (int, error) {
	for {
		_, _ = fmt.Fprintln(out, header)
		for i, option := range options {
			_, _ = fmt.Fprintf(out, "  %d) %s\n", i+1, option)
		}
		_, _ = fmt.Fprintf(out, "Choose 1-%d [%d]: ", len(options), defaultIndex+1)

		response, err := in.ReadString('\n')
		if err != nil {
			return 0, err
		}
		response = strings.TrimSpace(response)
		if response == "" {
			return defaultIndex, nil
		}
		choice, err := strconv.Atoi(response)
		if err == nil && choice >= 1 && choice <= len(options) {
			return choice - 1, nil
		}
		_, _ = fmt.Fprintf(out, "Please enter a number between 1 and %d\n", len(options))
	}
}

// Confirm prompts the user with a yes/no question and returns true for yes, false for no.
// It will keep prompting until a valid response is given.
// Empty input (just pressing Enter) defaults to yes.
func Confirm(prompt string) bool {
	confirmed, err := readConfirm(reader, os.Stdout, prompt)
	if err != nil {
		log.Fatalf("Failed to read input: %v", err)
	}
	return confirmed
}

func readConfirm(in *bufio.Reader, out io.Writer, prompt string) (bool, error) {
	for {
		_, _ = fmt.Fprint(out, prompt)
		response, err := in.ReadString('\n')
		if err != nil {
			return false, err
		}
		response = strings.TrimSpace(strings.ToLower(response))
		if response == "yes" || response == "y" || response == "" {
			return true, nil
		}
		if response == "no" || response == "n" {
			return false, nil
		}
		_, _ = fmt.Fprintln(out, "Please enter 'yes' or 'no'")
	}
}
