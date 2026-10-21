package cmd

import (
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"strings"

	"github.com/charlievieth/fastwalk"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/safefs"
	"github.com/spf13/cobra"
)

const (
	// The private agent context is the onyx-agent-context repo, cloned next to
	// the main onyx checkout. AGENTS.md documents the same lookup order.
	agentContextRepoName = "onyx-agent-context"
	agentContextCloneURL = "https://github.com/onyx-dot-app/onyx-agent-context.git"
	agentContextEnv      = "ONYX_AGENT_CONTEXT"
	// Fallback inside the checkout, for setups that see only the checkout,
	// such as the devcontainer.
	inRepoAgentContextDir = ".agent-context"
	// A checkout holds the agent context when it has this entry file.
	agentContextEntryFile = "AGENTS.md"
	// Older checkouts under the home directory, used with a warning when no
	// onyx-agent-context checkout exists: onyx-infra (the context lives in its
	// agent-context/ subdirectory) and the original onyx-llm-context repo.
	onyxInfraSkillSource = ".claude/skills/onyx-infra"
	legacySkillSource    = ".claude/skills/onyx-llm-context"
	agentContextDir      = "agent-context"
	claudeMDFile         = ".claude/CLAUDE.md"
	// Repo-relative home of on-demand skills. Claude, Codex and Cursor read
	// it through the .claude/skills, .codex/skills and .cursor/skills symlinks.
	projectSkillsDir = ".agents/skills"

	agentClaudeCode = "claude-code"
	agentCursor     = "cursor"
	agentCodex      = "codex"
)

// knownAgents maps each supported --agent value to its installer. Every
// installer regenerates its output, so reruns update in place.
var knownAgents = map[string]func(
	cmd *cobra.Command, ui *installUI, skills []agentContextSkill, repoRoot string, copyMode bool,
) error{
	agentClaudeCode: installClaudeSkills,
	agentCursor: func(
		cmd *cobra.Command, ui *installUI, skills []agentContextSkill, repoRoot string, _ bool,
	) error {
		return installCursorSkills(cmd, ui, skills, repoRoot)
	},
	agentCodex: installCodexSkills,
}

func NewInstallSkillCommand() *cobra.Command {
	var (
		source    string
		copyMode  bool
		cloneRepo bool
		noPull    bool
		agents    []string
	)

	cmd := &cobra.Command{
		Use:   "install-skill",
		Short: "Install Onyx agent-context skills for your coding agent",
		Long: `Install skills from the private onyx-agent-context repo for one or more
coding agents.

claude-code (default):
  Enforced skills (enforced/) are added as @imports in .claude/CLAUDE.md
  (project-scoped, git-ignored). Manual skills (skills/) are symlinked into
  .agents/skills/ of the repo (git-excluded; .claude/skills points there) and
  invoked via /skill-name.

cursor:
  Every skill is rendered as a rule in .cursor/rules/ (git-ignored).
  Enforced skills apply always; on-demand skills attach when Cursor matches
  their description, or on an explicit @skill-name mention.

codex:
  Enforced skills are compiled into .agents-local.md at the repo root
  (git-excluded; the committed AGENTS.md points agents at it), since Codex
  skills cannot be always-on. Manual skills are symlinked into
  .agents/skills/ of the repo (git-excluded; .codex/skills points there),
  invoked via $skill-name. A skill named like a committed one is skipped.

The checkout is fast-forwarded before installing, so a plain rerun picks up
new skills; --no-pull installs from the checkout as it is.

Without --source, the checkout is the first of: the path in
$ONYX_AGENT_CONTEXT, onyx-agent-context/ next to the main onyx checkout, and
.agent-context/ inside the checkout. --clone clones it next to the main
checkout, or inside the main checkout when that folder is the filesystem root
(the devcontainer) or not writable. Older
checkouts at ~/.claude/skills/onyx-infra and ~/.claude/skills/onyx-llm-context
still work, with a warning, until you clone the new one.`,
		Example: `  ods install-skill --clone
  ods install-skill --agent cursor
  ods install-skill --agent claude-code --agent cursor --agent codex
  ods install-skill --source /path/to/onyx-agent-context
  ods install-skill --copy`,
		RunE: func(cmd *cobra.Command, args []string) error {
			installers, err := resolveAgents(agents)
			if err != nil {
				return err
			}

			repoRoot, err := paths.GitRoot()
			if err != nil {
				return err
			}
			if source == "" {
				home, err := os.UserHomeDir()
				if err != nil {
					return fmt.Errorf("could not determine home directory: %w", err)
				}
				mainRoot, err := paths.MainCheckoutRoot()
				if err != nil {
					return err
				}
				found := findAgentContextSource(repoRoot, mainRoot, home)
				source = found.path
				if found.missing && cloneRepo {
					source = cloneDestination(mainRoot)
				}
				if found.legacy {
					if cloneRepo {
						source = cloneDestination(mainRoot)
					} else {
						_, _ = fmt.Fprintf(
							cmd.ErrOrStderr(),
							"Warning: using the older checkout at %s.\n"+
								"  Re-run with --clone to switch to %s.\n",
							source,
							agentContextRepoName,
						)
					}
				}
			}

			if _, err := os.Stat(source); os.IsNotExist(err) {
				if !cloneRepo {
					return fmt.Errorf("%s checkout not found at %s\n  Re-run with --clone to fetch it automatically", agentContextRepoName, source)
				}
				if err := cloneAgentContext(cmd, agentContextCloneURL, source); err != nil {
					return err
				}
			} else if !noPull {
				pullSource(cmd, source)
			}

			skills, err := discoverAgentContextSkills(source)
			if err != nil {
				return err
			}
			ui := newInstallUI(cmd.OutOrStdout())
			for _, install := range installers {
				if err := install(cmd, ui, skills, repoRoot, copyMode); err != nil {
					return err
				}
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&source, "source", "", "Path to the agent context checkout (default: see above)")
	cmd.Flags().BoolVar(&copyMode, "copy", false, "Copy files instead of symlinking (claude-code and codex manual skills)")
	cmd.Flags().BoolVar(&cloneRepo, "clone", false, fmt.Sprintf("Clone %s if not already present", agentContextCloneURL))
	cmd.Flags().BoolVar(&noPull, "no-pull", false, "Install from the checkout as it is, without updating it first")
	cmd.Flags().StringSliceVar(&agents, "agent", []string{agentClaudeCode}, "Agents to install for (repeatable): claude-code, cursor, codex")

	return cmd
}

// cloneAgentContext clones the agent context repo at url to dest. It is a full
// clone, since agents also branch and open PRs from it.
func cloneAgentContext(cmd *cobra.Command, url, dest string) error {
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Cloning %s → %s\n", url, dest)
	gitCmd := exec.Command("git", "clone", url, dest)
	gitCmd.Stdout = cmd.OutOrStdout()
	gitCmd.Stderr = cmd.ErrOrStderr()
	if err := gitCmd.Run(); err != nil {
		return fmt.Errorf(
			"git clone failed: %w\n  %s is a private repo; make sure you have access to it "+
				"and that git can authenticate to GitHub (for example with `gh auth login`)",
			err,
			agentContextRepoName,
		)
	}
	return nil
}

// pullSource fast-forwards the source checkout so a plain rerun picks up new
// skills without a separate git pull. Local work is never lost: --ff-only
// refuses diverged history, and git itself refuses a pull that would
// overwrite uncommitted changes. Any pull that cannot run (those cases,
// offline, no upstream) warns and installs from the local state, since a
// stale install is better than none. Local edits that do not conflict
// survive the update.
func pullSource(cmd *cobra.Command, source string) {
	// Not a git checkout (an exported copy, say): nothing to update.
	if _, err := os.Stat(filepath.Join(source, ".git")); os.IsNotExist(err) {
		return
	} else if err != nil {
		_, _ = fmt.Fprintf(
			cmd.ErrOrStderr(),
			"Warning: could not inspect %s (%v); installing without updating it.\n",
			source,
			err,
		)
		return
	}
	gitCmd := exec.Command("git", "-C", source, "pull", "--ff-only")
	out, err := gitCmd.CombinedOutput()
	if err != nil {
		_, _ = fmt.Fprintf(
			cmd.ErrOrStderr(),
			"Warning: could not update %s; installing from the local state.\n%s",
			source,
			out,
		)
		return
	}
	summary, _, _ := strings.Cut(strings.TrimSpace(string(out)), "\n")
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Pulled  %s (%s)\n", source, summary)
}

// resolveAgents maps the --agent values to installers, in the given order and
// deduplicated. An unknown agent is an error rather than a skip, so a typo
// never reads as a successful install.
func resolveAgents(agents []string) (
	[]func(*cobra.Command, *installUI, []agentContextSkill, string, bool) error, error,
) {
	var installers []func(*cobra.Command, *installUI, []agentContextSkill, string, bool) error
	seen := make(map[string]bool, len(agents))
	for _, agent := range agents {
		if seen[agent] {
			continue
		}
		seen[agent] = true
		install, ok := knownAgents[agent]
		if !ok {
			known := make([]string, 0, len(knownAgents))
			for name := range knownAgents {
				known = append(known, name)
			}
			return nil, fmt.Errorf(
				"unknown agent %q; known agents: %s", agent, strings.Join(known, ", "),
			)
		}
		installers = append(installers, install)
	}
	return installers, nil
}

func installClaudeSkills(
	cmd *cobra.Command, ui *installUI, skills []agentContextSkill, repoRoot string, copyMode bool,
) error {
	if err := installEnforcedSkills(cmd, skills, repoRoot); err != nil {
		return err
	}
	return linkManualSkills(cmd, ui, skills, repoRoot, copyMode)
}

// installEnforcedSkills writes @imports for all enforced skills into .claude/CLAUDE.md at the repo root.
func installEnforcedSkills(
	cmd *cobra.Command, skills []agentContextSkill, repoRoot string,
) error {
	var imports []string
	for _, skill := range skills {
		if skill.Enforced {
			imports = append(imports, fmt.Sprintf("@%s", skill.File))
		}
	}

	if len(imports) == 0 {
		return nil
	}

	destFile := filepath.Join(repoRoot, claudeMDFile)

	content := strings.Join(imports, "\n") + "\n"
	existing, err := os.ReadFile(destFile)
	if err == nil && string(existing) == content {
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Up to date %s\n", destFile)
		return nil
	}

	if err := safefs.WriteFileNoFollow(repoRoot, destFile, []byte(content), 0o644); err != nil {
		return fmt.Errorf("could not write %s: %w", destFile, err)
	}
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Installed %s\n", destFile)
	return nil
}

// linkManualSkills symlinks each on-demand skill directory into the repo's
// .agents/skills, which .claude/skills, .codex/skills and .cursor/skills point
// at. The links are git-excluded, and a skill named like a committed one is
// skipped, so an install never dirties the tree or replaces a repo skill.
func linkManualSkills(
	cmd *cobra.Command, ui *installUI, skills []agentContextSkill, repoRoot string, copyMode bool,
) error {
	if len(skills) == 0 {
		return nil
	}
	// Claude and Codex share one directory; one pass is enough.
	if ui.manualSkillsLinked {
		return nil
	}
	ui.manualSkillsLinked = true

	var candidates []agentContextSkill
	for _, skill := range skills {
		if !skill.Enforced {
			candidates = append(candidates, skill)
		}
	}

	skillsDir := filepath.Join(repoRoot, projectSkillsDir)
	if _, err := os.Stat(skillsDir); os.IsNotExist(err) {
		// Nothing installed here before, so nothing to clean up either.
		if len(candidates) == 0 {
			return nil
		}
		// The user may pick another directory, so every check below runs
		// against the resolved one.
		if skillsDir, err = ui.resolveTargetDir("Agent skills", skillsDir); err != nil {
			return err
		}
	}

	// Resolve symlinks (.claude/skills points at .agents/skills) so git
	// paths and exclusions name the real location.
	realDir, err := filepath.EvalSymlinks(skillsDir)
	if err != nil {
		return fmt.Errorf("could not resolve %s: %w", skillsDir, err)
	}
	skillsDir = realDir
	realRoot, err := filepath.EvalSymlinks(repoRoot)
	if err != nil {
		return fmt.Errorf("could not resolve %s: %w", repoRoot, err)
	}
	// A directory outside the repo has no committed files to protect and
	// nothing git could show as untracked.
	dirRel, err := filepath.Rel(realRoot, skillsDir)
	inRepo := err == nil && dirRel != ".." && !strings.HasPrefix(dirRel, ".."+string(filepath.Separator))

	manual := candidates
	if inRepo {
		manual = nil
		for _, skill := range candidates {
			rel := path.Join(filepath.ToSlash(dirRel), skill.Name)
			tracked, err := isTrackedByGit(realRoot, rel)
			if err != nil {
				return err
			}
			if tracked {
				_, _ = fmt.Fprintf(
					cmd.ErrOrStderr(),
					"Warning: skipping skill %q: %s is committed in this repo.\n", skill.Name, rel,
				)
				continue
			}
			manual = append(manual, skill)
		}

		// The exclusion comes first, so a failure leaves nothing untracked behind.
		patterns := make([]string, 0, len(manual))
		for _, skill := range manual {
			patterns = append(patterns, "/"+path.Join(filepath.ToSlash(dirRel), skill.Name))
		}
		if err := excludeFromGit(realRoot, patterns...); err != nil {
			return err
		}
	}

	// Every skill sits at <source>/<tier>/<name>, so any of them names the
	// source checkout that stale links of past installs point into. Cleanup
	// runs even when the manual tier emptied, so its old links go too.
	source := filepath.Dir(filepath.Dir(skills[0].Dir))
	if err := removeStaleSkillLinks(cmd, skillsDir, ownedSkillRoots(source), manual); err != nil {
		return err
	}

	for _, skill := range manual {
		srcDir := skill.Dir
		dstDir := filepath.Join(skillsDir, skill.Name)

		if copyMode {
			if err := copySkill(srcDir, dstDir); err != nil {
				return fmt.Errorf("could not copy %s: %w", skill.Name, err)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Copied  %s\n", dstDir)
			continue
		}

		if fi, err := os.Lstat(dstDir); err == nil {
			if fi.Mode()&os.ModeSymlink != 0 {
				_ = os.Remove(dstDir)
			} else if err := os.RemoveAll(dstDir); err != nil {
				return fmt.Errorf("could not remove existing %s: %w", dstDir, err)
			}
		}
		rel, err := filepath.Rel(skillsDir, srcDir)
		if err != nil {
			return fmt.Errorf("could not compute relative path for %s: %w", skill.Name, err)
		}

		if err := os.Symlink(rel, dstDir); err != nil {
			if copyErr := copySkill(srcDir, dstDir); copyErr != nil {
				return fmt.Errorf("could not install %s: %w", skill.Name, copyErr)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Copied  %s (symlink failed)\n", dstDir)
			continue
		}
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Linked  %s -> %s\n", dstDir, rel)
	}

	return nil
}

// ownedSkillRoots are the checkouts whose skill links install-skill manages:
// the current source and the older checkouts under home, so links left by an
// install from an older checkout are cleaned up after switching.
func ownedSkillRoots(source string) []string {
	roots := []string{source}
	if home, err := os.UserHomeDir(); err == nil {
		roots = append(roots,
			filepath.Join(home, onyxInfraSkillSource),
			filepath.Join(home, legacySkillSource),
		)
	}
	return roots
}

// removeStaleSkillLinks deletes symlinks in skillsDir that resolve into one of
// roots but no longer match an on-demand skill — the ownership test for a link,
// since only this command links from there. Hand-written entries, links to
// other places and past --copy installs are left alone.
func removeStaleSkillLinks(
	cmd *cobra.Command, skillsDir string, roots []string, manual []agentContextSkill,
) error {
	current := make(map[string]bool, len(manual))
	for _, skill := range manual {
		current[skill.Name] = true
	}
	entries, err := os.ReadDir(skillsDir)
	if err != nil {
		return fmt.Errorf("could not read %s: %w", skillsDir, err)
	}
	for _, entry := range entries {
		if current[entry.Name()] || entry.Type()&os.ModeSymlink == 0 {
			continue
		}
		path := filepath.Join(skillsDir, entry.Name())
		target, err := os.Readlink(path)
		if err != nil {
			return fmt.Errorf("could not read link %s: %w", path, err)
		}
		if !filepath.IsAbs(target) {
			target = filepath.Join(skillsDir, target)
		}
		if !insideAny(roots, filepath.Clean(target)) {
			continue
		}
		if err := os.Remove(path); err != nil {
			return fmt.Errorf("could not remove stale skill link %s: %w", path, err)
		}
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Removed %s\n", path)
	}
	return nil
}

// isTrackedByGit reports whether git tracks anything at the repo-relative
// path. A failing git is an error, never an answer of "not tracked", since the
// caller would then replace what may be a committed file.
func isTrackedByGit(repoRoot, rel string) (bool, error) {
	gitCmd := exec.Command("git", "ls-files", "--", rel)
	gitCmd.Dir = repoRoot
	out, err := gitCmd.Output()
	if err != nil {
		return false, fmt.Errorf("could not check whether %s is committed: %w", rel, err)
	}
	return strings.TrimSpace(string(out)) != "", nil
}

func copySkill(srcDir, dstDir string) error {
	// fastwalk visits a directory before its children, so each destination
	// directory exists by the time its entries are copied.
	return fastwalk.Walk(nil, srcDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(srcDir, path)
		dst := filepath.Join(dstDir, rel)
		if d.IsDir() {
			return os.MkdirAll(dst, 0o755)
		}
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(dst, content, 0o644)
	})
}

// insideAny reports whether path is inside one of roots.
func insideAny(roots []string, path string) bool {
	for _, root := range roots {
		rel, err := filepath.Rel(root, path)
		if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return true
		}
	}
	return false
}
