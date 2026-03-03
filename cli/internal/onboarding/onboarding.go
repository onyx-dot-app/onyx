// Package onboarding handles the first-run setup flow for Onyx CLI.
package onboarding

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/tui"
	"golang.org/x/term"
)

var (
	boldStyle    = lipgloss.NewStyle().Bold(true)
	dimStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("#555577"))
	greenStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#00cc66")).Bold(true)
	redStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("#ff5555")).Bold(true)
	yellowStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#ffcc00"))
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
	_ = tui.RenderSplashOnboarding(w, h)
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

	// API Key
	fmt.Println()
	fmt.Println("  " + dimStyle.Render("Need an API key? Press Enter to open the admin panel in your browser,"))
	fmt.Println("  " + dimStyle.Render("or paste your key below."))
	fmt.Println()

	apiKey := prompt(reader, "  API key", cfg.APIKey)

	if apiKey == "" {
		// Open browser to API key page
		url := strings.TrimRight(serverURL, "/") + "/admin/api-key"
		fmt.Printf("\n  Opening %s ...\n", url)
		openBrowser(url)
		fmt.Println("  " + dimStyle.Render("Copy your API key, then paste it here."))
		fmt.Println()

		apiKey = prompt(reader, "  API key", "")
		if apiKey == "" {
			fmt.Println("\n  " + redStyle.Render("No API key provided. Exiting."))
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
	success, detail := client.TestConnection()

	if success {
		if err := config.Save(cfg); err != nil {
			fmt.Println("  " + redStyle.Render("Could not save config: "+err.Error()))
		}
		fmt.Println("  " + greenStyle.Render(detail))
		fmt.Println()
		printQuickStart()
		return &cfg
	}

	fmt.Println("  " + redStyle.Render("Connection failed.") + " " + detail)
	fmt.Println()
	fmt.Println("  " + dimStyle.Render("Run ")+boldStyle.Render("onyx-cli configure")+dimStyle.Render(" to try again."))
	return nil
}

func prompt(reader *bufio.Reader, label, defaultVal string) string {
	if defaultVal != "" {
		fmt.Printf("%s %s: ", label, dimStyle.Render("["+defaultVal+"]"))
	} else {
		fmt.Printf("%s: ", label)
	}

	line, err := reader.ReadString('\n')
	if err != nil {
		return defaultVal
	}
	line = strings.TrimSpace(line)
	if line == "" {
		return defaultVal
	}
	return line
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

func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "linux":
		cmd = exec.Command("xdg-open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	}
	if cmd != nil {
		_ = cmd.Start()
	}
}
