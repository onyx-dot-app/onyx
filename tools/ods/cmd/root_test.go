package cmd

import (
	"io"
	"testing"

	log "github.com/sirupsen/logrus"
)

func TestNewRootCommand_debugSetsTheLogLevel(t *testing.T) {
	previous := log.GetLevel()
	t.Cleanup(func() { log.SetLevel(previous) })

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
