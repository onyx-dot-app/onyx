package cmd

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/charlievieth/fastwalk"
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

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

func runWebScript(args []string) {
	webDir, err := webDir()
	if err != nil {
		log.Fatalf("Failed to find web directory: %v", err)
	}

	if needsInstall, reason := nodeModulesNeedsInstall(webDir); needsInstall {
		log.Infof("%s, running bun install --frozen-lockfile...", reason)
		installCmd := exec.Command("bun", "install", "--frozen-lockfile")
		installCmd.Dir = webDir
		installCmd.Stdout = os.Stdout
		installCmd.Stderr = os.Stderr
		installCmd.Stdin = os.Stdin
		if err := installCmd.Run(); err != nil {
			log.Fatalf("Failed to run bun install: %v", err)
		}
		writeLockStamp(webDir)
	}

	ensureWorkspaceLibsBuilt(webDir)

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
	webCmd.Stdout = os.Stdout
	webCmd.Stderr = os.Stderr
	webCmd.Stdin = os.Stdin

	if err := webCmd.Run(); err != nil {
		// For wrapped commands, preserve the child process's exit code and
		// avoid duplicating already-printed stderr output.
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			if code := exitErr.ExitCode(); code != -1 {
				os.Exit(code)
			}
		}
		log.Fatalf("Failed to run bun: %v", err)
	}
}

// lockStampName is the file inside node_modules recording the sha256 of the
// bun.lock that produced it. node_modules lives in a persistent volume in the
// devcontainer, so it routinely outlives lockfile updates in the workspace —
// the stamp is what lets us notice.
const lockStampName = ".ods-bun-lock-sha256"

// nodeModulesNeedsInstall reports whether bun install should be run, along with
// a human-readable reason. Install is needed when node_modules is missing,
// empty, or was installed from a different bun.lock than the current one.
func nodeModulesNeedsInstall(webDir string) (bool, string) {
	nodeModules := filepath.Join(webDir, "node_modules")
	entries, err := os.ReadDir(nodeModules)
	if errors.Is(err, os.ErrNotExist) {
		return true, "node_modules not found"
	}
	if err != nil {
		// Couldn't read the directory for some other reason; let bun install
		// attempt to sort it out rather than silently skipping.
		return true, fmt.Sprintf("could not read node_modules (%v)", err)
	}
	if len(entries) == 0 {
		return true, "node_modules is empty"
	}

	lockHash, err := fileSHA256(filepath.Join(webDir, "bun.lock"))
	if err != nil {
		// No lockfile to compare against; nothing more we can check.
		return false, ""
	}
	stamp, err := os.ReadFile(filepath.Join(nodeModules, lockStampName))
	if err != nil || strings.TrimSpace(string(stamp)) != lockHash {
		return true, "node_modules is stale (bun.lock changed since last install)"
	}
	return false, ""
}

// writeLockStamp records the current bun.lock hash after a successful install.
// Best-effort: a failure only means the next run reinstalls, which is safe.
//
// The stamp is replaced via temp file + rename rather than written in place:
// the devcontainer's node_modules volume is shared across sessions that may
// run as different users (root agent sessions, the dev user), and an in-place
// write to a stamp owned by the other user fails — which would silently force
// a reinstall on every run. Rename needs only directory write permission and
// atomically replaces the previous owner's file.
func writeLockStamp(webDir string) {
	lockHash, err := fileSHA256(filepath.Join(webDir, "bun.lock"))
	if err != nil {
		return
	}
	nodeModules := filepath.Join(webDir, "node_modules")
	stampPath := filepath.Join(nodeModules, lockStampName)
	tmp, err := os.CreateTemp(nodeModules, lockStampName+".tmp-*")
	if err != nil {
		log.Debugf("Failed to create stamp temp file in %s: %v", nodeModules, err)
		return
	}
	_, writeErr := tmp.WriteString(lockHash + "\n")
	// World-readable so sessions running as other users can validate it.
	chmodErr := tmp.Chmod(0o644)
	closeErr := tmp.Close()
	if writeErr != nil || chmodErr != nil || closeErr != nil {
		_ = os.Remove(tmp.Name())
		log.Debugf("Failed to write stamp temp file %s: %v/%v/%v", tmp.Name(), writeErr, chmodErr, closeErr)
		return
	}
	if err := os.Rename(tmp.Name(), stampPath); err != nil {
		_ = os.Remove(tmp.Name())
		log.Debugf("Failed to replace %s: %v", stampPath, err)
	}
}

func fileSHA256(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
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
		needsBuild, reason := libNeedsBuild(pkgDir)
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

// libNeedsBuild reports whether a workspace library's dist/ is missing or
// stale relative to its sources, along with a human-readable reason. The
// staleness check compares newest mtimes, walking the package excluding its
// build output, dependencies, and hidden entries — cheap enough (a few
// thousand stats at most) to run before every script.
func libNeedsBuild(pkgDir string) (bool, string) {
	if _, err := os.Stat(pkgDir); err != nil {
		// Not a checkout that has this package; nothing to do.
		return false, ""
	}
	distNewest, err := newestMtime(filepath.Join(pkgDir, "dist"), nil)
	if errors.Is(err, os.ErrNotExist) {
		return true, "has no dist build"
	}
	if err != nil {
		return true, fmt.Sprintf("dist is unreadable (%v)", err)
	}
	srcNewest, err := newestMtime(pkgDir, map[string]bool{"dist": true, "node_modules": true})
	if err != nil {
		return false, ""
	}
	if srcNewest.After(distNewest) {
		return true, "dist build is older than its sources"
	}
	return false, ""
}

// newestMtime returns the newest modification time under root, skipping
// directories named in excludeDirs and hidden entries.
func newestMtime(root string, excludeDirs map[string]bool) (time.Time, error) {
	var newest time.Time
	// fastwalk runs the callback on several goroutines, so guard the running max.
	var mu sync.Mutex
	err := fastwalk.Walk(nil, root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		name := d.Name()
		if path != root && (excludeDirs[name] || strings.HasPrefix(name, ".")) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		mu.Lock()
		if info.ModTime().After(newest) {
			newest = info.ModTime()
		}
		mu.Unlock()
		return nil
	})
	return newest, err
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
