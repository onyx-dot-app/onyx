package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

type webPackageJSON struct {
	Scripts map[string]string `json:"scripts"`
}

// NewWebCommand creates a command that runs npm scripts from the web directory.
func NewWebCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "web <script> [args...]",
		Short: "Run web/package.json npm scripts",
		Long: `Run npm scripts from web/package.json.

Examples:
  ods web dev
  ods web lint
  ods web test -- --watch`,
		Args: cobra.MinimumNArgs(1),
		ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
			if len(args) > 0 {
				return nil, cobra.ShellCompDirectiveNoFileComp
			}
			return webScriptNames(), cobra.ShellCompDirectiveNoFileComp
		},
		Run: func(cmd *cobra.Command, args []string) {
			runWebScript(args)
		},
	}

	return cmd
}

func runWebScript(args []string) {
	webDir, err := webDir()
	if err != nil {
		log.Fatalf("Failed to find web directory: %v", err)
	}

	npmArgs := append([]string{"run"}, args...)
	log.Debugf("Running in %s: npm %v", webDir, npmArgs)

	webCmd := exec.Command("npm", npmArgs...)
	webCmd.Dir = webDir
	webCmd.Stdout = os.Stdout
	webCmd.Stderr = os.Stderr
	webCmd.Stdin = os.Stdin

	if err := webCmd.Run(); err != nil {
		log.Fatalf("web command failed: %v", err)
	}
}

func webScriptNames() []string {
	scripts, err := loadWebScripts()
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

func loadWebScripts() (map[string]string, error) {
	webDir, err := webDir()
	if err != nil {
		return nil, err
	}

	packageJSONPath := filepath.Join(webDir, "package.json")
	data, err := os.ReadFile(packageJSONPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read %s: %w", packageJSONPath, err)
	}

	var pkg webPackageJSON
	if err := json.Unmarshal(data, &pkg); err != nil {
		return nil, fmt.Errorf("failed to parse %s: %w", packageJSONPath, err)
	}

	if pkg.Scripts == nil {
		return nil, nil
	}

	return pkg.Scripts, nil
}

func webDir() (string, error) {
	root, err := paths.GitRoot()
	if err != nil {
		return "", err
	}
	return filepath.Join(root, "web"), nil
}
