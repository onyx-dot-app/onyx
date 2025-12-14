package prompt

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	log "github.com/sirupsen/logrus"
)

// reader is the input reader, can be replaced for testing
var reader = bufio.NewReader(os.Stdin)

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
