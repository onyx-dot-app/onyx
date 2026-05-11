// Package onboarding handles the first-run setup flow for Onyx CLI.
package onboarding

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/browser"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/tui"
	"golang.org/x/term"
)

var (
	boldStyle   = tui.BoldStyle
	dimStyle    = tui.DimStyle
	greenStyle  = tui.GreenStyle
	redStyle    = tui.RedStyle
	yellowStyle = tui.YellowStyle
)

func getTermSize() (int, int) {
	w, h, err := term.GetSize(int(os.Stdout.Fd()))
	if err != nil {
		return 80, 24
	}
	return w, h
}

// Run executes the interactive onboarding flow.
// Returns the validated config, or nil if the user cancels.
func Run(existing *config.OnyxCliConfig) *config.OnyxCliConfig {
	cfg := config.DefaultConfig()
	if existing != nil {
		cfg = *existing
	}

	w, h := getTermSize()
	fmt.Print(tui.RenderSplashOnboarding(w, h))

	fmt.Println()
	fmt.Println("  Welcome to " + boldStyle.Render("Onyx CLI") + ".")
	fmt.Println()

	reader := bufio.NewReader(os.Stdin)

	// Server URL
	serverURL := prompt(reader, "  Onyx server URL", cfg.ServerURL)
	if serverURL == "" {
		return nil
	}
	if !strings.HasPrefix(serverURL, "http://") && !strings.HasPrefix(serverURL, "https://") {
		fmt.Println("  " + redStyle.Render("Server URL must start with http:// or https://"))
		return nil
	}

	// Personal Access Token
	fmt.Println()
	fmt.Println("  " + dimStyle.Render("Need a personal access token (PAT)? Press Enter to open the admin panel"))
	fmt.Println("  " + dimStyle.Render("in your browser, or paste your PAT below."))
	fmt.Println()

	apiKey := promptSecret("  Personal access token", cfg.APIKey)

	if apiKey == "" {
		// Open browser to PAT page
		url := config.WebOrigin(serverURL) + "/app/settings/accounts-access"
		fmt.Printf("\n  Opening %s ...\n", url)
		browser.OpenBrowser(url)
		fmt.Println("  " + dimStyle.Render("Copy your personal access token, then paste it here."))
		fmt.Println()

		apiKey = promptSecret("  Personal access token", "")
		if apiKey == "" {
			fmt.Println("\n  " + redStyle.Render("No personal access token provided. Exiting."))
			return nil
		}
	}

	// Test connection
	cfg = config.OnyxCliConfig{
		ServerURL:        serverURL,
		APIKey:           apiKey,
		DefaultAgentID: cfg.DefaultAgentID,
	}

	fmt.Println("\n  " + yellowStyle.Render("Testing connection..."))

	client := api.NewClient(cfg)
	if err := client.TestConnection(context.Background()); err != nil {
		fmt.Println("  " + redStyle.Render("Connection failed.") + " " + err.Error())
		fmt.Println()
		fmt.Println("  " + dimStyle.Render("Run ") + boldStyle.Render("onyx-cli configure") + dimStyle.Render(" to try again."))
		return nil
	}

	if err := config.Save(cfg); err != nil {
		fmt.Println("  " + redStyle.Render("Could not save config: "+err.Error()))
		return nil
	}
	fmt.Println("  " + greenStyle.Render("Connected and authenticated."))
	fmt.Println()
	printQuickStart()
	return &cfg
}

func promptSecret(label, defaultVal string) string {
	if defaultVal != "" {
		fmt.Printf("%s %s: ", label, dimStyle.Render("[hidden]"))
	} else {
		fmt.Printf("%s: ", label)
	}

	password, err := term.ReadPassword(int(os.Stdin.Fd()))
	fmt.Println() // ReadPassword doesn't echo a newline
	if err != nil {
		return defaultVal
	}
	line := strings.TrimSpace(string(password))
	if line == "" {
		return defaultVal
	}
	return line
}

func prompt(reader *bufio.Reader, label, defaultVal string) string {
	if defaultVal != "" {
		fmt.Printf("%s %s: ", label, dimStyle.Render("["+defaultVal+"]"))
	} else {
		fmt.Printf("%s: ", label)
	}

	line, err := reader.ReadString('\n')
	// ReadString may return partial data along with an error (e.g. EOF without newline)
	line = strings.TrimSpace(line)
	if line != "" {
		return line
	}
	if err != nil {
		return defaultVal
	}
	return defaultVal
}

func printQuickStart() {
	fmt.Println("  " + boldStyle.Render("Quick start"))
	fmt.Println()
	fmt.Println("  Just type to chat with your Onyx agent.")
	fmt.Println()

	rows := [][2]string{
		{"/help", "Show all commands"},
		{"/attach", "Attach a file"},
		{"/agent", "Switch agent"},
		{"/new", "New conversation"},
		{"/sessions", "Browse previous chats"},
		{"Esc", "Cancel generation"},
		{"Ctrl+D", "Quit"},
	}
	for _, r := range rows {
		fmt.Printf("    %-12s %s\n", boldStyle.Render(r[0]), dimStyle.Render(r[1]))
	}
	fmt.Println()
}

