package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/bunpkg"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/childproc"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

type webPackageJSON struct {
	Scripts map[string]string `json:"scripts"`
}

// NewWebCommand creates a command that runs bun scripts from the web directory.
func NewWebCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "web <script> [args...]",
		Short: "Run web/package.json bun scripts",
		Long:  webHelpDescription(),
		Args:  cobra.MinimumNArgs(1),
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
	cmd.Flags().SetInterspersed(false)

	return cmd
}

// prepareWebDir returns the web directory once its dependencies and workspace
// library builds are current.
func prepareWebDir() string {
	webDir, err := paths.WebDir()
	if err != nil {
		log.Fatalf("Failed to find web directory: %v", err)
	}

	if needsInstall, reason := bunpkg.NodeModulesNeedsInstall(webDir); needsInstall {
		log.Infof("%s, running bun install --frozen-lockfile...", reason)
		installCmd := exec.Command("bun", "install", "--frozen-lockfile")
		installCmd.Dir = webDir
		childproc.Run(installCmd, "bun install")
		bunpkg.WriteLockStamp(webDir)
	}

	ensureWorkspaceLibsBuilt(webDir)

	return webDir
}

func runWebScript(args []string) {
	webDir := prepareWebDir()

	scriptName := args[0]
	scriptArgs := args[1:]
	if len(scriptArgs) > 0 && scriptArgs[0] == "--" {
		scriptArgs = scriptArgs[1:]
	}

	bunArgs := []string{"run", scriptName}
	if len(scriptArgs) > 0 {
		// bun requires "--" to forward flags to the underlying script.
		bunArgs = append(bunArgs, "--")
		bunArgs = append(bunArgs, scriptArgs...)
	}
	log.Debugf("Running in %s: bun %v", webDir, bunArgs)

	webCmd := exec.Command("bun", bunArgs...)
	webCmd.Dir = webDir
	childproc.Run(webCmd, "bun")
}

// webLibPackages are the bun workspace packages whose exports point at their
// dist/ build output. bun install links them into node_modules but never runs
// their builds, so a fresh checkout (or an edit to their sources) leaves the
// dev server failing on unresolvable exports. Order matters: opal's build
// consumes shared's output.
var webLibPackages = []string{"lib/shared", "lib/opal"}

// ensureWorkspaceLibsBuilt builds each workspace library whose dist/ is
// missing or older than its sources.
func ensureWorkspaceLibsBuilt(webDir string) {
	for _, rel := range webLibPackages {
		pkgDir := filepath.Join(webDir, rel)
		needsBuild, reason := bunpkg.LibNeedsBuild(pkgDir)
		if !needsBuild {
			continue
		}
		log.Infof("web/%s %s, running bun run build...", rel, reason)
		buildCmd := exec.Command("bun", "run", "build")
		buildCmd.Dir = pkgDir
		buildCmd.Stdout = os.Stdout
		buildCmd.Stderr = os.Stderr
		if err := buildCmd.Run(); err != nil {
			log.Fatalf("Failed to build web/%s: %v", rel, err)
		}
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

func webHelpDescription() string {
	description := `Run bun scripts from web/package.json.

Examples:
  ods web dev
  ods web lint
  ods web test --watch`

	scripts := webScriptNames()
	if len(scripts) == 0 {
		return description + "\n\nAvailable scripts: (unable to load)"
	}

	return description + "\n\nAvailable scripts:\n  " + strings.Join(scripts, "\n  ")
}

func loadWebScripts() (map[string]string, error) {
	webDir, err := paths.WebDir()
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
