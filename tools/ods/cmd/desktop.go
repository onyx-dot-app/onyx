package cmd

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

type desktopPackageJSON struct {
	Scripts map[string]string `json:"scripts"`
}

// NewDesktopCommand creates a command that runs npm scripts from the desktop directory.
func NewDesktopCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "desktop <script> [args...]",
		Short: "Run desktop/package.json npm scripts",
		Long:  desktopHelpDescription(),
		Args:  cobra.MinimumNArgs(1),
		ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
			if len(args) > 0 {
				return nil, cobra.ShellCompDirectiveNoFileComp
			}
			return desktopScriptNames(), cobra.ShellCompDirectiveNoFileComp
		},
		Run: func(cmd *cobra.Command, args []string) {
			runDesktopScript(args)
		},
	}
	cmd.Flags().SetInterspersed(false)

	return cmd
}

func runDesktopScript(args []string) {
	desktopDir, err := desktopDir()
	if err != nil {
		log.Fatalf("Failed to find desktop directory: %v", err)
	}

	scriptName := args[0]
	scriptArgs := args[1:]
	if len(scriptArgs) > 0 && scriptArgs[0] == "--" {
		scriptArgs = scriptArgs[1:]
	}

	npmArgs := []string{"run", scriptName}
	if len(scriptArgs) > 0 {
		// npm requires "--" to forward flags to the underlying script.
		npmArgs = append(npmArgs, "--")
		npmArgs = append(npmArgs, scriptArgs...)
	}
	log.Debugf("Running in %s: npm %v", desktopDir, npmArgs)

	desktopCmd := exec.Command("npm", npmArgs...)
	desktopCmd.Dir = desktopDir
	desktopCmd.Stdout = os.Stdout
	desktopCmd.Stderr = os.Stderr
	desktopCmd.Stdin = os.Stdin

	if err := desktopCmd.Run(); err != nil {
		// For wrapped commands, preserve the child process's exit code and
		// avoid duplicating already-printed stderr output.
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			if code := exitErr.ExitCode(); code != -1 {
				os.Exit(code)
			}
		}
		log.Fatalf("Failed to run npm: %v", err)
	}
}

func desktopScriptNames() []string {
	scripts, err := loadDesktopScripts()
	if err != nil {
		return nil
	}

	names := make([]string, 0, len(scripts))
	for name := range scripts {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func desktopHelpDescription() string {
	description := `Run npm scripts from desktop/package.json.

Examples:
  ods desktop dev
  ods desktop build
  ods desktop build:dmg`

	scripts := desktopScriptNames()
	if len(scripts) == 0 {
		return description + "\n\nAvailable scripts: (unable to load)"
	}

	return description + "\n\nAvailable scripts:\n  " + strings.Join(scripts, "\n  ")
}

func loadDesktopScripts() (map[string]string, error) {
	desktopDir, err := desktopDir()
	if err != nil {
		return nil, err
	}

	packageJSONPath := filepath.Join(desktopDir, "package.json")
	data, err := os.ReadFile(packageJSONPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read %s: %w", packageJSONPath, err)
	}

	var pkg desktopPackageJSON
	if err := json.Unmarshal(data, &pkg); err != nil {
		return nil, fmt.Errorf("failed to parse %s: %w", packageJSONPath, err)
	}

	if pkg.Scripts == nil {
		return nil, nil
	}

	return pkg.Scripts, nil
}

func desktopDir() (string, error) {
	root, err := paths.GitRoot()
	if err != nil {
		return "", err
	}
	return filepath.Join(root, "desktop"), nil
}
