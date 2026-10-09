// Package dockercmd shells out to docker / docker compose for the deploy
// commands: command detection, sudo fallback on Linux, and the compose
// invocations the install lifecycle needs.
package dockercmd

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sort"
	"strings"
)

// Command describes one external process invocation.
type Command struct {
	Name string
	Args []string
	// Dir is the working directory ("" = inherit).
	Dir string
	// Env entries are merged over the current process environment. When the
	// invocation is wrapped in sudo they are passed as argv to `env` instead,
	// so sudo's env_reset cannot strip them.
	Env map[string]string
	// Stdout/Stderr stream output when set; otherwise output is captured
	// (stdout into Result, stderr into the returned error).
	Stdout io.Writer
	Stderr io.Writer
}

// Result holds captured output for non-streaming invocations.
type Result struct {
	Stdout string
}

// Runner executes commands. The production implementation is ExecRunner;
// tests substitute a fake recording invocations.
type Runner interface {
	Run(ctx context.Context, c Command) (Result, error)
}

// ExecRunner runs commands with os/exec.
type ExecRunner struct{}

var _ Runner = ExecRunner{}

func (ExecRunner) Run(ctx context.Context, c Command) (Result, error) {
	cmd := exec.CommandContext(ctx, c.Name, c.Args...)
	cmd.Dir = c.Dir
	cmd.Env = mergedEnv(c.Env)

	var stdout, stderr strings.Builder
	if c.Stdout != nil {
		cmd.Stdout = c.Stdout
	} else {
		cmd.Stdout = &stdout
	}
	if c.Stderr != nil {
		cmd.Stderr = c.Stderr
	} else {
		cmd.Stderr = &stderr
	}

	err := cmd.Run()
	if err != nil && c.Stderr == nil && stderr.Len() > 0 {
		err = fmt.Errorf("%w: %s", err, strings.TrimSpace(stderr.String()))
	}
	return Result{Stdout: stdout.String()}, err
}

func mergedEnv(extra map[string]string) []string {
	if len(extra) == 0 {
		return nil // inherit as-is
	}
	env := os.Environ()
	for _, k := range sortedKeys(extra) {
		env = append(env, k+"="+extra[k])
	}
	return env
}

// sortedKeys keeps env ordering deterministic for tests and logs.
func sortedKeys(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
