package cmd

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

// checkWorkspaceSetupSource checks working files and the index, or a specific
// incoming commit. The index includes sparse paths and intentionally keeps an
// unstaged deletion from making a workspace source look like a skill-only one.
func checkWorkspaceSetupSource(source, revision string) error {
	resolved, err := filepath.EvalSymlinks(source)
	if err != nil {
		return fmt.Errorf("could not inspect source %s: %w", source, err)
	}
	source, err = filepath.Abs(resolved)
	if err != nil {
		return fmt.Errorf("could not resolve source path: %w", err)
	}
	checkout, err := skillSourceCheckout(source)
	if err != nil {
		return err
	}
	roots := []string{source, filepath.Join(source, agentContextDir)}
	if checkout != "" && checkout != source {
		roots = append(roots, checkout, filepath.Join(checkout, agentContextDir))
	}
	candidates := make(map[string]string)
	var paths []string
	for _, root := range roots {
		setup := filepath.Join(root, "scripts", "setup_agents.py")
		if info, err := os.Stat(setup); err == nil && !info.IsDir() {
			return workspaceSetupRequired(root)
		} else if err != nil && !os.IsNotExist(err) && !errors.Is(err, syscall.ENOTDIR) {
			return fmt.Errorf("could not inspect setup entry point %s: %w", setup, err)
		}
		if checkout == "" {
			continue
		}
		relative, err := filepath.Rel(checkout, setup)
		if err != nil {
			return fmt.Errorf("could not resolve setup entry point %s: %w", setup, err)
		}
		relative = filepath.ToSlash(relative)
		if _, exists := candidates[relative]; !exists {
			candidates[relative] = root
			paths = append(paths, relative)
		}
	}
	if checkout == "" {
		return nil
	}

	args := []string{"--literal-pathspecs", "-C", checkout}
	if revision == "" {
		args = append(args, "ls-files", "--stage", "-z")
	} else {
		args = append(args, "ls-tree", "-z", revision)
	}
	args = append(args, "--")
	args = append(args, paths...)
	out, err := exec.Command("git", args...).CombinedOutput()
	if err != nil {
		return fmt.Errorf("could not inspect source setup entries: %w\n%s", err, out)
	}
	for _, entry := range strings.Split(string(out), "\x00") {
		if entry == "" {
			continue
		}
		metadata, path, ok := strings.Cut(entry, "\t")
		if !ok {
			return fmt.Errorf("invalid Git setup entry in %s", checkout)
		}
		if root, exists := candidates[path]; exists &&
			(strings.HasPrefix(metadata, "100") || strings.HasPrefix(metadata, "120000 ")) {
			return workspaceSetupRequired(root)
		}
	}
	return nil
}

// A .git directory or gitfile identifies the owning checkout without treating
// failures to read real repository metadata as an exported, non-Git source.
func skillSourceCheckout(source string) (string, error) {
	for root := source; ; root = filepath.Dir(root) {
		if _, err := os.Stat(filepath.Join(root, ".git")); err == nil {
			return root, nil
		} else if !os.IsNotExist(err) {
			return "", fmt.Errorf("could not inspect source checkout %s: %w", root, err)
		}
		if filepath.Dir(root) == root {
			return "", nil
		}
	}
}

func workspaceSetupRequired(root string) error {
	return fmt.Errorf(
		"this source uses workspace setup; ods install-skill cannot install it\n"+
			"  Follow %s and use its setup entry point: %s",
		filepath.Join(root, "README.md"), filepath.Join(root, "scripts", "setup_agents.py"),
	)
}
