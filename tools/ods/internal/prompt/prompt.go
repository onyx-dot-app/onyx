package prompt

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/tui"
)

// reader is the input reader, can be replaced for testing
var reader = bufio.NewReader(os.Stdin)

// String prompts the user for a free-form line of input. Re-prompts until a
// non-empty value is entered.
func String(prompt string) string {
	for {
		fmt.Print(prompt)
		response, err := reader.ReadString('\n')
		if err != nil {
			log.Fatalf("Failed to read input: %v", err)
		}
		response = strings.TrimSpace(response)
		if response != "" {
			return response
		}
		fmt.Println("Value cannot be empty.")
	}
}

// Select asks the user to choose one of options and returns its index. The
// options are shown as an arrow-key list; when the terminal cannot run one
// (piped input, CI, no TTY) it falls back to the numbered Choose prompt. The
// second return is false when the user cancels the list, which the numbered
// fallback cannot do.
func Select(title string, options []string, defaultIndex int) (int, bool) {
	index, err := tui.Select(title, options, defaultIndex)
	if err != nil {
		log.Debugf("Arrow-key select unavailable: %v", err)
		return Choose(title, options, defaultIndex), true
	}
	if index < 0 {
		return 0, false
	}
	return index, true
}

// Choose prompts the user with a numbered list of options and returns the
// index of the chosen one. Empty input selects defaultIndex. It re-prompts
// until the input names an option.
func Choose(header string, options []string, defaultIndex int) int {
	for {
		fmt.Println(header)
		for i, option := range options {
			fmt.Printf("  %d) %s\n", i+1, option)
		}
		fmt.Printf("Choose 1-%d [%d]: ", len(options), defaultIndex+1)

		response, err := reader.ReadString('\n')
		if err != nil {
			log.Fatalf("Failed to read input: %v", err)
		}
		response = strings.TrimSpace(response)
		if response == "" {
			return defaultIndex
		}
		choice, err := strconv.Atoi(response)
		if err == nil && choice >= 1 && choice <= len(options) {
			return choice - 1
		}
		fmt.Printf("Please enter a number between 1 and %d\n", len(options))
	}
}

// Confirm prompts the user with a yes/no question and returns true for yes, false for no.
// It will keep prompting until a valid response is given.
// Empty input (just pressing Enter) defaults to yes.
func Confirm(prompt string) bool {
	for {
		fmt.Print(prompt)
		response, err := reader.ReadString('\n')
		if err != nil {
			log.Fatalf("Failed to read input: %v", err)
		}
		response = strings.TrimSpace(strings.ToLower(response))
		if response == "yes" || response == "y" || response == "" {
			return true
		}
		if response == "no" || response == "n" {
			return false
		}
		fmt.Println("Please enter 'yes' or 'no'")
	}
}
