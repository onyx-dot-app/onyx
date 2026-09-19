package docker

import (
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
)

// fakeDocker puts a shell script named docker first on PATH. The script
// appends each invocation's argv, one call per line, to the returned calls
// file and then runs body.
func fakeDocker(t *testing.T, body string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake docker is a shell script")
	}
	dir := t.TempDir()
	calls := filepath.Join(dir, "calls")
	script := "#!/bin/sh\necho \"$*\" >> \"$(dirname \"$0\")/calls\"\n" + body + "\n"
	if err := os.WriteFile(filepath.Join(dir, "docker"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	return calls
}

func readCalls(t *testing.T, calls string) []string {
	t.Helper()
	data, err := os.ReadFile(calls)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

func TestFindPostgresContainer(t *testing.T) {
	tests := []struct {
		name    string
		body    string
		want    string
		wantErr string
	}{
		{
			name: "prefers the project container",
			body: `[ "$1" = inspect ] && echo true`,
			want: "proj-relational_db-1",
		},
		{
			name: "falls back to legacy names in order",
			body: `if [ "$1" = inspect ]; then
  case "$4" in
    onyx-relational_db-1|relational_db) echo true ;;
    *) echo false ;;
  esac
fi`,
			want: "onyx-relational_db-1",
		},
		{
			name: "falls back to any container running a postgres image",
			body: `[ "$1" = inspect ] && exit 1
printf 'web\tnginx:1.27\ndb\tpostgres:15.2-alpine\n'`,
			want: "db",
		},
		{
			name: "errors when nothing matches",
			body: `[ "$1" = inspect ] && exit 1
printf 'web\tnginx:1.27\nmalformed\n'`,
			wantErr: `no running PostgreSQL container found for project "proj"; try: ods compose dev`,
		},
		{
			name:    "errors when docker ps fails",
			body:    "exit 1",
			wantErr: `no running PostgreSQL container found for project "proj"; try: ods compose dev`,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			fakeDocker(t, tt.body)

			got, err := FindPostgresContainer("proj")
			if tt.wantErr != "" {
				if err == nil || err.Error() != tt.wantErr {
					t.Fatalf("expected error %q, got %q, %v", tt.wantErr, got, err)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestFindPostgresContainer_queriesDockerInOrder(t *testing.T) {
	calls := fakeDocker(t, "exit 1")

	_, _ = FindPostgresContainer("proj")

	want := []string{
		"inspect -f {{.State.Running}} proj-relational_db-1",
		"inspect -f {{.State.Running}} onyx_postgres",
		"inspect -f {{.State.Running}} onyx-relational_db-1",
		"inspect -f {{.State.Running}} onyx-stack-relational_db-1",
		"inspect -f {{.State.Running}} docker_compose-relational_db-1",
		"inspect -f {{.State.Running}} relational_db",
		"ps --format {{.Names}}\t{{.Image}}",
	}
	if got := readCalls(t, calls); !slices.Equal(got, want) {
		t.Fatalf("expected calls %q, got %q", want, got)
	}
}

func TestExecCommands_buildDockerArgs(t *testing.T) {
	tests := []struct {
		name string
		run  func() error
		want string
	}{
		{
			name: "Exec",
			run:  func() error { return Exec("db", "psql", "-c", "select 1") },
			want: "exec -i db psql -c select 1",
		},
		{
			name: "ExecWithEnv",
			run: func() error {
				return ExecWithEnv("db", map[string]string{"PGPASSWORD": "secret"}, "pg_dump", "-U", "postgres")
			},
			want: "exec -i -e PGPASSWORD=secret db pg_dump -U postgres",
		},
		{
			name: "CopyFromContainer",
			run:  func() error { return CopyFromContainer("db", "/tmp/dump.sql", "out.sql") },
			want: "cp db:/tmp/dump.sql out.sql",
		},
		{
			name: "CopyToContainer",
			run:  func() error { return CopyToContainer("db", "in.sql", "/tmp/in.sql") },
			want: "cp in.sql db:/tmp/in.sql",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			calls := fakeDocker(t, "")
			if err := tt.run(); err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got := readCalls(t, calls); !slices.Equal(got, []string{tt.want}) {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestExecCommands_returnDockerFailure(t *testing.T) {
	fakeDocker(t, "exit 3")
	for name, err := range map[string]error{
		"Exec":              Exec("db", "true"),
		"ExecWithEnv":       ExecWithEnv("db", nil, "true"),
		"CopyFromContainer": CopyFromContainer("db", "/a", "b"),
		"CopyToContainer":   CopyToContainer("db", "a", "/b"),
	} {
		if err == nil || err.Error() != "exit status 3" {
			t.Errorf("%s: expected %q, got %v", name, "exit status 3", err)
		}
	}
}

func TestExecOutput(t *testing.T) {
	t.Run("returns stdout", func(t *testing.T) {
		calls := fakeDocker(t, "echo 'PostgreSQL 15.2'")
		got, err := ExecOutput("db", "psql", "--version")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got != "PostgreSQL 15.2\n" {
			t.Fatalf("expected %q, got %q", "PostgreSQL 15.2\n", got)
		}
		if got := readCalls(t, calls); !slices.Equal(got, []string{"exec -i db psql --version"}) {
			t.Fatalf("unexpected calls %q", got)
		}
	})

	t.Run("includes stderr in the error", func(t *testing.T) {
		fakeDocker(t, "echo 'role missing' >&2; exit 2")
		got, err := ExecOutput("db", "psql")
		if err == nil || err.Error() != "exit status 2: role missing\n" {
			t.Fatalf("expected %q, got %q, %v", "exit status 2: role missing\n", got, err)
		}
	})
}

func TestGetContainerIP(t *testing.T) {
	tests := []struct {
		name    string
		body    string
		want    string
		wantErr string
	}{
		{name: "first network wins", body: "echo '172.18.0.2 10.0.0.3 '", want: "172.18.0.2"},
		{name: "no networks", body: "echo ' '", wantErr: "container db has no IP address"},
		{name: "inspect fails", body: "exit 1", wantErr: "failed to get container IP: exit status 1"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			calls := fakeDocker(t, tt.body)
			got, err := GetContainerIP("db")
			if tt.wantErr != "" {
				if err == nil || err.Error() != tt.wantErr {
					t.Fatalf("expected error %q, got %q, %v", tt.wantErr, got, err)
				}
				return
			}
			if err != nil || got != tt.want {
				t.Fatalf("expected %q, got %q, %v", tt.want, got, err)
			}
			want := "inspect -f {{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}} db"
			if got := readCalls(t, calls); !slices.Equal(got, []string{want}) {
				t.Fatalf("expected calls %q, got %q", want, got)
			}
		})
	}
}

func TestGetHostPort(t *testing.T) {
	tests := []struct {
		name    string
		body    string
		want    int
		wantErr string
	}{
		{name: "uses the first mapping", body: `printf '0.0.0.0:15432\n[::]:15433\n'`, want: 15432},
		{name: "not running", body: "exit 1", wantErr: "docker port db 5432: exit status 1"},
		{name: "not exposed", body: "true", wantErr: "port 5432 not exposed on db"},
		{name: "no colon", body: "echo garbage", wantErr: "unexpected docker port output: garbage"},
		{name: "non-numeric port", body: "echo 0.0.0.0:abc", wantErr: "invalid port number in docker port output: 0.0.0.0:abc"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			calls := fakeDocker(t, tt.body)
			got, err := GetHostPort("db", 5432)
			if got := readCalls(t, calls); !slices.Equal(got, []string{"port db 5432"}) {
				t.Fatalf("expected calls %q, got %q", "port db 5432", got)
			}
			if tt.wantErr != "" {
				if err == nil || err.Error() != tt.wantErr {
					t.Fatalf("expected error %q, got %d, %v", tt.wantErr, got, err)
				}
				return
			}
			if err != nil || got != tt.want {
				t.Fatalf("expected %d, got %d, %v", tt.want, got, err)
			}
		})
	}
}

func TestIsPortExposed(t *testing.T) {
	calls := fakeDocker(t, `[ "$2" = web ] && echo 0.0.0.0:3000`)

	if !IsPortExposed("web", "3000") {
		t.Fatal("expected web:3000 to be exposed")
	}
	if IsPortExposed("db", "5432") {
		t.Fatal("expected db:5432 not to be exposed")
	}
	want := []string{"port web 3000", "port db 5432"}
	if got := readCalls(t, calls); !slices.Equal(got, want) {
		t.Fatalf("expected calls %q, got %q", want, got)
	}
}
