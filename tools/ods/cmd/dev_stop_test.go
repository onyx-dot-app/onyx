package cmd

import (
	"slices"
	"strings"
	"testing"
)

func TestRunDevStop(t *testing.T) {
	tests := []struct {
		name     string
		docker   string
		wantStop bool
		wantErr  string
		wantLogs string
	}{
		{
			name:     "running container",
			docker:   `if [ "$1" = ps ]; then echo abc123; fi`,
			wantStop: true,
			wantLogs: "level=info msg=Stopping devcontainer abc123...\nlevel=info msg=Devcontainer stopped\n",
		},
		{
			name:     "no running container",
			wantLogs: "level=info msg=No running devcontainer found\n",
		},
		{
			name:    "docker ps fails",
			docker:  "exit 3",
			wantErr: "Failed to find devcontainer: exit status 3",
		},
		{
			name:     "docker stop fails",
			docker:   `if [ "$1" = ps ]; then echo abc123; else exit 1; fi`,
			wantStop: true,
			wantErr:  "Failed to stop devcontainer: exit status 1",
			wantLogs: "level=info msg=Stopping devcontainer abc123...\n",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bin := composeFakeBin(t)
			composeFakeTool(t, bin, "docker", tt.docker)
			root := composeRepo(t)
			logs := composeCaptureLog(t)

			var err error
			if tt.wantErr == "" {
				command := newDevStopCommand()
				command.SetArgs([]string{})
				if err := command.Execute(); err != nil {
					t.Fatal(err)
				}
			} else {
				err = runDevStop()
			}

			if tt.wantErr != "" && (err == nil || err.Error() != tt.wantErr) {
				t.Fatalf("expected error %q, got %v", tt.wantErr, err)
			}
			want := []string{"ps -q --filter label=devcontainer.local_folder=" + root}
			if tt.wantStop {
				want = append(want, "stop abc123")
			}
			if got := composeCalls(t, bin, "docker"); !slices.Equal(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
			if logs.String() != tt.wantLogs {
				t.Fatalf("expected logs %q, got %q", tt.wantLogs, logs.String())
			}
		})
	}

	t.Run("outside a git repo", func(t *testing.T) {
		bin := composeFakeBin(t)
		composeFakeTool(t, bin, "docker", "")
		composeNoRepo(t)
		err := runDevStop()
		if err == nil || !strings.HasPrefix(err.Error(), "Failed to find git root: ") {
			t.Fatalf("expected a git root error, got %v", err)
		}
		if calls := composeCalls(t, bin, "docker"); calls != nil {
			t.Fatalf("expected no docker calls, got %q", calls)
		}
	})
}
