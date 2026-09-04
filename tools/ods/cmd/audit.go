package cmd

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

// auditBinary is the standalone auditor installed by the `audit` extra.
const auditBinary = "ods-audit"

// installHint tells the user how to get the auditor.
const installHint = `The auditor ships separately because its scanner is most of the download.

Install it with the "audit" extra:

  uv tool install 'onyx-devtools[audit]'

or run it without installing:

  uv run --with 'onyx-devtools[audit]' ods audit`

// NewAuditCommand creates the `ods audit` command, a pass-through to the
// `ods-audit` binary. Flag parsing stays off so every argument, including
// --help, reaches the real command.
func NewAuditCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "audit",
		Short: "Audit dependencies for known vulnerabilities (needs onyx-devtools[audit])",
		Long: `Audit dependencies for known vulnerabilities.

Runs the ` + auditBinary + ` binary from the onyx-devtools "audit" extra, which
scans lockfiles, container images, Dependabot alerts, and pinned GitHub Actions.
Run "` + auditBinary + ` --help" for the full reference.`,
		DisableFlagParsing: true,
		Args:               cobra.ArbitraryArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runAudit(cmd, args)
		},
	}
}

func runAudit(cmd *cobra.Command, args []string) {
	bin, err := resolveAuditBinary()
	if err != nil {
		if wantsHelp(args) {
			_ = cmd.Help()
		}
		log.Errorf("%s is not installed.", auditBinary)
		fmt.Fprintln(os.Stderr, installHint)
		os.Exit(1)
	}

	c := exec.Command(bin, args...)
	c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := c.Run(); err != nil {
		// Pass the exit code through: `ods audit` gates deploys on it.
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			os.Exit(exitErr.ExitCode())
		}
		log.Fatalf("Failed to run %s: %v", bin, err)
	}
}

// resolveAuditBinary finds the auditor next to this binary, then on PATH.
func resolveAuditBinary() (string, error) {
	exeDir := ""
	if exe, err := os.Executable(); err == nil {
		exeDir = filepath.Dir(exe)
	}
	return lookupAuditBinary(exeDir)
}

// lookupAuditBinary prefers the auditor in exeDir so a venv that has both wheels
// works even when it is not on PATH.
func lookupAuditBinary(exeDir string) (string, error) {
	name := auditBinary
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	if exeDir != "" {
		sibling := filepath.Join(exeDir, name)
		if info, err := os.Stat(sibling); err == nil && !info.IsDir() {
			return sibling, nil
		}
	}
	return exec.LookPath(auditBinary)
}

func wantsHelp(args []string) bool {
	for _, a := range args {
		if a == "-h" || a == "--help" {
			return true
		}
	}
	return len(args) == 0
}
