package cmd

import (
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func composeSkipUnlessLinux(t *testing.T) {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("the socket and remote user rules under test are Linux specific")
	}
}

// composeDevEnv clears the variables that the devcontainer helpers read and
// write, so that the test restores them when it ends.
func composeDevEnv(t *testing.T) {
	t.Helper()
	for _, key := range []string{"DOCKER_HOST", "DOCKER_SOCK", "DEVCONTAINER_REMOTE_USER", "SSH_AUTH_SOCK"} {
		t.Setenv(key, "")
	}
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir())
}

func composeTouch(t *testing.T, path string) string {
	t.Helper()
	writeFile(t, path, "")
	return path
}

func TestDetectDockerSock(t *testing.T) {
	composeSkipUnlessLinux(t)
	tests := []struct {
		name       string
		dockerHost string
		xdgSock    bool
		want       string // "XDG" means the socket in XDG_RUNTIME_DIR
		wantWarn   bool
	}{
		{name: "unix scheme", dockerHost: "unix:///run/user/5/docker.sock", xdgSock: true, want: "/run/user/5/docker.sock"},
		{name: "bare path", dockerHost: "/custom/docker.sock", xdgSock: true, want: "/custom/docker.sock"},
		{name: "tcp falls back to XDG socket", dockerHost: "tcp://127.0.0.1:2375", xdgSock: true, want: "XDG", wantWarn: true},
		{name: "empty unix scheme falls back", dockerHost: "unix://", xdgSock: true, want: "XDG", wantWarn: true},
		{name: "XDG socket without DOCKER_HOST", xdgSock: true, want: "XDG"},
		{name: "standard socket as last fallback", want: "/var/run/docker.sock"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			composeDevEnv(t)
			logs := composeCaptureLog(t)
			t.Setenv("DOCKER_HOST", tt.dockerHost)
			xdgSock := filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "docker.sock")
			if tt.xdgSock {
				composeTouch(t, xdgSock)
			}
			want := tt.want
			if want == "XDG" {
				want = xdgSock
			}

			if got := detectDockerSock(); got != want {
				t.Fatalf("expected %q, got %q", want, got)
			}
			warning := "level=warning msg=DOCKER_HOST=\"" + tt.dockerHost + "\" is not a unix socket path; falling back to local socket detection"
			if got := strings.Contains(logs.String(), warning); got != tt.wantWarn {
				t.Fatalf("expected warning %v, got logs %q", tt.wantWarn, logs.String())
			}
		})
	}
}

func TestEnsureDockerSock(t *testing.T) {
	composeSkipUnlessLinux(t)

	t.Run("keeps an existing value", func(t *testing.T) {
		composeDevEnv(t)
		t.Setenv("DOCKER_SOCK", "/already/set.sock")
		ensureDockerSock()
		if got := os.Getenv("DOCKER_SOCK"); got != "/already/set.sock" {
			t.Fatalf("expected the existing value, got %q", got)
		}
	})

	t.Run("sets the detected socket", func(t *testing.T) {
		composeDevEnv(t)
		t.Setenv("DOCKER_HOST", "unix:///detected.sock")
		ensureDockerSock()
		if got := os.Getenv("DOCKER_SOCK"); got != "/detected.sock" {
			t.Fatalf("expected /detected.sock, got %q", got)
		}
	})
}

func TestEnsureRemoteUser(t *testing.T) {
	composeSkipUnlessLinux(t)
	tests := []struct {
		name      string
		existing  string
		sockInXDG bool
		want      string
	}{
		{name: "rootless socket under XDG_RUNTIME_DIR", sockInXDG: true, want: "root"},
		{name: "standard socket", want: ""},
		{name: "existing value wins", existing: "dev", sockInXDG: true, want: "dev"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			composeDevEnv(t)
			t.Setenv("DEVCONTAINER_REMOTE_USER", tt.existing)
			sock := "/var/run/docker.sock"
			if tt.sockInXDG {
				sock = filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "docker.sock")
			}
			t.Setenv("DOCKER_SOCK", sock)

			ensureRemoteUser()

			if got := os.Getenv("DEVCONTAINER_REMOTE_USER"); got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestWorktreeGitMount(t *testing.T) {
	t.Run("no .git", func(t *testing.T) {
		if mount, ok := worktreeGitMount(t.TempDir()); ok || mount != "" {
			t.Fatalf("expected no mount, got %q, %v", mount, ok)
		}
	})

	t.Run("regular repository", func(t *testing.T) {
		root := composeRepo(t)
		if mount, ok := worktreeGitMount(root); ok || mount != "" {
			t.Fatalf("expected no mount, got %q, %v", mount, ok)
		}
	})

	t.Run("linked worktree", func(t *testing.T) {
		main := composeRepo(t)
		gittest.Commit(t, main, "file.txt")
		worktree := filepath.Join(filepath.Dir(main), "linked")
		gittest.Git(t, main, "worktree", "add", worktree)

		mount, ok := worktreeGitMount(worktree)

		common := filepath.Join(main, ".git")
		want := "type=bind,source=" + common + ",target=" + common
		if !ok || mount != want {
			t.Fatalf("expected %q, got %q, %v", want, mount, ok)
		}
	})

	t.Run("relative git dir", func(t *testing.T) {
		root := composeRepo(t)
		if err := os.Rename(filepath.Join(root, ".git"), filepath.Join(root, "gitdir")); err != nil {
			t.Fatal(err)
		}
		writeFile(t, filepath.Join(root, ".git"), "gitdir: gitdir\n")

		mount, ok := worktreeGitMount(root)

		common := filepath.Join(root, "gitdir")
		want := "type=bind,source=" + common + ",target=" + common
		if !ok || mount != want {
			t.Fatalf("expected %q, got %q, %v", want, mount, ok)
		}
	})

	t.Run("broken .git file", func(t *testing.T) {
		composeNoRepo(t)
		root := t.TempDir()
		writeFile(t, filepath.Join(root, ".git"), "gitdir: /does/not/exist\n")
		logs := composeCaptureLog(t)

		if mount, ok := worktreeGitMount(root); ok || mount != "" {
			t.Fatalf("expected no mount, got %q, %v", mount, ok)
		}
		if !strings.Contains(logs.String(), "level=warning msg=Failed to detect git common dir: exit status ") {
			t.Fatalf("expected a warning, got %q", logs.String())
		}
	})
}

func TestSSHAgentMount(t *testing.T) {
	if runtime.GOOS == "darwin" {
		t.Skip("macOS uses the Docker Desktop helper socket")
	}

	t.Run("unset", func(t *testing.T) {
		composeDevEnv(t)
		logs := composeCaptureLog(t)
		if mount, ok := sshAgentMount(); ok || mount != "" {
			t.Fatalf("expected no mount, got %q, %v", mount, ok)
		}
		want := "level=warning msg=SSH_AUTH_SOCK not set — SSH agent forwarding disabled (git over SSH won't work inside the container)\n"
		if logs.String() != want {
			t.Fatalf("expected %q, got %q", want, logs.String())
		}
	})

	t.Run("missing socket", func(t *testing.T) {
		composeDevEnv(t)
		logs := composeCaptureLog(t)
		sock := filepath.Join(t.TempDir(), "agent.sock")
		t.Setenv("SSH_AUTH_SOCK", sock)
		if mount, ok := sshAgentMount(); ok || mount != "" {
			t.Fatalf("expected no mount, got %q, %v", mount, ok)
		}
		want := "level=warning msg=SSH_AUTH_SOCK=" + sock + " not accessible — SSH agent forwarding disabled: stat " + sock + ": no such file or directory\n"
		if logs.String() != want {
			t.Fatalf("expected %q, got %q", want, logs.String())
		}
	})

	t.Run("accessible socket", func(t *testing.T) {
		composeDevEnv(t)
		sock := composeTouch(t, filepath.Join(t.TempDir(), "agent.sock"))
		t.Setenv("SSH_AUTH_SOCK", sock)
		mount, ok := sshAgentMount()
		want := "type=bind,source=" + sock + ",target=/tmp/ssh-agent.sock"
		if !ok || mount != want {
			t.Fatalf("expected %q, got %q, %v", want, mount, ok)
		}
	})
}

// composeFakeDevcontainer installs a devcontainer fake that records its argv
// and the remote user it receives, then runs body.
func composeFakeDevcontainer(t *testing.T, body string) string {
	t.Helper()
	bin := composeFakeBin(t)
	record := `echo "USER=$DEVCONTAINER_REMOTE_USER SOCK=$DOCKER_SOCK" >> "` + filepath.Join(bin, "devcontainer.env") + `"`
	composeFakeTool(t, bin, "devcontainer", record+"\n"+body)
	return bin
}

func TestDevcontainerCommands(t *testing.T) {
	tests := []struct {
		name     string
		args     []string
		wantArgs string
	}{
		{name: "up", wantArgs: "up --workspace-folder ROOT"},
		{name: "restart", wantArgs: "up --workspace-folder ROOT --remove-existing-container"},
		{name: "exec after --", args: []string{"--", "ls", "-la"}, wantArgs: "exec --workspace-folder ROOT ls -la"},
		{name: "exec passes flags through", args: []string{"-it", "echo", "hi"}, wantArgs: "exec --workspace-folder ROOT -it echo hi"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			composeDevEnv(t)
			bin := composeFakeDevcontainer(t, "")
			root := composeRepo(t)

			command := newDevUpCommand()
			switch {
			case tt.name == "restart":
				command = newDevRestartCommand()
			case tt.args != nil:
				command = newDevExecCommand()
			}
			command.SetArgs(append([]string{}, tt.args...))
			if err := command.Execute(); err != nil {
				t.Fatal(err)
			}

			want := []string{strings.ReplaceAll(tt.wantArgs, "ROOT", root)}
			if got := composeCalls(t, bin, "devcontainer"); !slices.Equal(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestRunDevcontainer_rootlessDockerAndMounts(t *testing.T) {
	composeSkipUnlessLinux(t)
	composeDevEnv(t)
	bin := composeFakeDevcontainer(t, "")
	main := composeRepo(t)
	gittest.Commit(t, main, "file.txt")
	worktree := filepath.Join(filepath.Dir(main), "linked")
	gittest.Git(t, main, "worktree", "add", worktree)
	t.Chdir(worktree)
	xdgSock := composeTouch(t, filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "docker.sock"))
	agentSock := composeTouch(t, filepath.Join(t.TempDir(), "agent.sock"))
	t.Setenv("SSH_AUTH_SOCK", agentSock)

	if err := runDevcontainer("up", []string{"--extra"}); err != nil {
		t.Fatal(err)
	}

	common := filepath.Join(main, ".git")
	wantArgs := []string{"up --workspace-folder " + worktree +
		" --mount type=bind,source=" + common + ",target=" + common +
		" --mount type=bind,source=" + agentSock + ",target=/tmp/ssh-agent.sock --extra"}
	if got := composeCalls(t, bin, "devcontainer"); !slices.Equal(got, wantArgs) {
		t.Fatalf("expected %q, got %q", wantArgs, got)
	}
	wantEnv := "USER=root SOCK=" + xdgSock + "\n"
	if got := composeReadFile(t, filepath.Join(bin, "devcontainer.env")); got != wantEnv {
		t.Fatalf("expected %q, got %q", wantEnv, got)
	}
}

func TestRunDevcontainer_errors(t *testing.T) {
	t.Run("devcontainer fails", func(t *testing.T) {
		composeDevEnv(t)
		composeFakeDevcontainer(t, "exit 4")
		composeRepo(t)
		err := runDevcontainer("up", nil)
		if err == nil || err.Error() != "devcontainer up failed: exit status 4" {
			t.Fatalf("expected the devcontainer failure, got %v", err)
		}
	})

	t.Run("outside a git repo", func(t *testing.T) {
		composeDevEnv(t)
		bin := composeFakeDevcontainer(t, "")
		composeNoRepo(t)
		err := runDevcontainer("up", nil)
		if err == nil || !strings.HasPrefix(err.Error(), "Failed to find git root: ") {
			t.Fatalf("expected a git root error, got %v", err)
		}
		if calls := composeCalls(t, bin, "devcontainer"); calls != nil {
			t.Fatalf("expected no devcontainer calls, got %q", calls)
		}
	})
}

func TestDevcontainerImage(t *testing.T) {
	tests := []struct {
		name       string
		config     string // "" means no devcontainer.json
		want       string
		wantPrefix string
	}{
		{name: "image", config: `{"image": "ghcr.io/onyx/dev:1"}`, want: "ghcr.io/onyx/dev:1"},
		{name: "missing file", wantPrefix: "Failed to read devcontainer.json: "},
		{name: "invalid JSON", config: `{`, wantPrefix: "Failed to parse devcontainer.json: "},
		{name: "no image", config: `{"name": "onyx"}`, wantPrefix: "No image field in devcontainer.json"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			root := composeRepo(t)
			if tt.config != "" {
				writeFile(t, filepath.Join(root, ".devcontainer", "devcontainer.json"), tt.config)
			}
			got, err := devcontainerImage()
			if tt.wantPrefix == "" {
				if err != nil || got != tt.want {
					t.Fatalf("expected %q, got %q, %v", tt.want, got, err)
				}
				return
			}
			if err == nil || !strings.HasPrefix(err.Error(), tt.wantPrefix) {
				t.Fatalf("expected error starting with %q, got %v", tt.wantPrefix, err)
			}
		})
	}

	t.Run("outside a git repo", func(t *testing.T) {
		composeNoRepo(t)
		if _, err := devcontainerImage(); err == nil || !strings.HasPrefix(err.Error(), "Failed to find git root: ") {
			t.Fatalf("expected a git root error, got %v", err)
		}
	})
}

func TestRunDevRebuild(t *testing.T) {
	tests := []struct {
		name     string
		pull     string
		wantWarn bool
	}{
		{name: "pull succeeds"},
		{name: "pull fails", pull: "exit 1", wantWarn: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			composeDevEnv(t)
			bin := composeFakeDevcontainer(t, "")
			composeFakeTool(t, bin, "docker", tt.pull)
			root := composeRepo(t)
			writeFile(t, filepath.Join(root, ".devcontainer", "devcontainer.json"), `{"image": "onyx/dev:2"}`)
			logs := composeCaptureLog(t)

			command := newDevRebuildCommand()
			command.SetArgs([]string{})
			if err := command.Execute(); err != nil {
				t.Fatal(err)
			}

			if got := composeCalls(t, bin, "docker"); !slices.Equal(got, []string{"pull onyx/dev:2"}) {
				t.Fatalf("expected one pull, got %q", got)
			}
			wantUp := []string{"up --workspace-folder " + root + " --remove-existing-container"}
			if got := composeCalls(t, bin, "devcontainer"); !slices.Equal(got, wantUp) {
				t.Fatalf("expected %q, got %q", wantUp, got)
			}
			warning := "level=warning msg=Failed to pull image (continuing with local copy): exit status 1\n"
			if got := strings.Contains(logs.String(), warning); got != tt.wantWarn {
				t.Fatalf("expected warning %v, got logs %q", tt.wantWarn, logs.String())
			}
		})
	}

	t.Run("invalid devcontainer.json", func(t *testing.T) {
		bin := composeFakeDevcontainer(t, "")
		composeFakeTool(t, bin, "docker", "")
		composeRepo(t)
		err := runDevRebuild()
		if err == nil || !strings.HasPrefix(err.Error(), "Failed to read devcontainer.json: ") {
			t.Fatalf("expected a read error, got %v", err)
		}
		if calls := composeCalls(t, bin, "docker"); calls != nil {
			t.Fatalf("expected no docker calls, got %q", calls)
		}
	})
}
