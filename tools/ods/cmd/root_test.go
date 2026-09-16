package cmd

import (
	"io"
	"testing"

	log "github.com/sirupsen/logrus"
)

// restoreLogger puts the standard logger back the way it was when the test
// ends. Root commands change its level and formatter.
func restoreLogger(t *testing.T) {
	t.Helper()
	logger := log.StandardLogger()
	out, formatter, level := logger.Out, logger.Formatter, logger.GetLevel()
	t.Cleanup(func() {
		logger.SetOutput(out)
		logger.SetFormatter(formatter)
		logger.SetLevel(level)
	})
}

func TestNewRootCommand_debugSetsTheLogLevel(t *testing.T) {
	restoreLogger(t)

	for _, c := range []struct {
		args []string
		want log.Level
	}{
		{[]string{"--debug"}, log.DebugLevel},
		{[]string{}, log.InfoLevel},
	} {
		root := NewRootCommand()
		root.SetArgs(c.args)
		root.SetOut(io.Discard)
		if err := root.Execute(); err != nil {
			t.Fatalf("Execute: %v", err)
		}
		if got := log.GetLevel(); got != c.want {
			t.Fatalf("expected %q with args %q, got %q", c.want, c.args, got)
		}
	}
}
