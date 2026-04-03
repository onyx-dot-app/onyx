package config

import "fmt"

// Experiment describes an experimental feature flag.
type Experiment struct {
	Name    string
	Flag    string // CLI flag name
	EnvVar  string // environment variable name
	Config  string // JSON path in config file
	Enabled bool
	Desc    string
}

// Experiments returns the list of available experimental features
// with their current status based on the given feature flags.
func Experiments(f Features) []Experiment {
	return []Experiment{
		{
			Name:    "Stream Markdown",
			Flag:    "--stream-markdown",
			EnvVar:  EnvStreamMarkdown,
			Config:  "features.stream_markdown",
			Enabled: f.StreamMarkdown,
			Desc:    "Render markdown progressively as the response streams in",
		},
	}
}

// ExperimentsText formats the experiments list for display.
func ExperimentsText(f Features) string {
	exps := Experiments(f)
	text := "Experimental Features\n\n"
	for _, e := range exps {
		status := "off"
		if e.Enabled {
			status = "on"
		}
		text += fmt.Sprintf("  %-20s [%s]\n", e.Name, status)
		text += fmt.Sprintf("    %s\n", e.Desc)
		text += fmt.Sprintf("    flag: %s  env: %s  config: %s\n\n", e.Flag, e.EnvVar, e.Config)
	}
	text += "Enable via CLI flag, environment variable, or config file.\n"
	text += "Example: onyx-cli chat --stream-markdown"
	return text
}
