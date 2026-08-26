package cmd

import (
	tea "charm.land/bubbletea/v2"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/starprompt"
	"github.com/onyx-dot-app/onyx/cli/internal/tui"
	"github.com/spf13/cobra"
)

func newChatCmd() *cobra.Command {
	var (
		noStreamMarkdown bool
		chatAgentID      int
		chatAgentName    string
	)

	cmd := &cobra.Command{
		Use:   "chat",
		Short: "Launch the interactive chat TUI (requires terminal)",
		Long: `Launch the interactive terminal UI for chatting with your Onyx agent.
On first run, an interactive setup wizard will guide you through configuration.`,
		Example: `  onyx-cli chat
  onyx-cli chat --agent-name "Support Agent"`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()

			// CLI flag overrides config/env
			if cmd.Flags().Changed("no-stream-markdown") {
				v := !noStreamMarkdown
				cfg.Features.StreamMarkdown = &v
			}

			if cmd.Flags().Changed("agent-id") || cmd.Flags().Changed("agent-name") {
				if !cfg.IsConfigured() {
					return exitcodes.New(exitcodes.NotConfigured,
						"--agent-id and --agent-name require a configured CLI; run onyx-cli chat to complete setup first")
				}
				client := api.NewClient(cfg)
				agentID, _, err := resolveAgentSelection(
					cmd.Context(),
					client,
					chatAgentID,
					cmd.Flags().Changed("agent-id"),
					chatAgentName,
					cmd.Flags().Changed("agent-name"),
					cfg.DefaultAgentID,
				)
				if err != nil {
					return err
				}
				cfg.DefaultAgentID = agentID
			}

			starprompt.MaybePrompt()

			var m tui.Model
			if !config.ConfigExists() || !cfg.IsConfigured() {
				m = tui.NewFirstRunModel(cfg)
			} else {
				m = tui.NewModel(cfg, api.NewClient(cfg))
			}

			p := tea.NewProgram(m)
			_, err := p.Run()
			return err
		},
	}

	cmd.Flags().BoolVar(&noStreamMarkdown, "no-stream-markdown", false, "Disable progressive markdown rendering during streaming")
	cmd.Flags().IntVar(&chatAgentID, "agent-id", 0, "Agent ID to use for this session")
	cmd.Flags().StringVar(&chatAgentName, "agent-name", "", "Agent name to use for this session (exact or unique substring)")

	return cmd
}
