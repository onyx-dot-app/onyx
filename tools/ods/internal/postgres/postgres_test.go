package postgres

import (
	"os"
	"slices"
	"testing"
)

func TestIsLoopbackHost(t *testing.T) {
	for _, host := range []string{"localhost", "LOCALHOST", "localhost.", "  localhost. ", "127.0.0.1", "127.0.0.2", "127.255.255.254", "127.0.0.2.", "::1", "[::1]", "::ffff:127.0.0.2", "[::ffff:127.0.0.2]"} {
		if !IsLoopbackHost(host) {
			t.Errorf("loopback %q classified as remote", host)
		}
	}
	for _, host := range []string{"", "remote.example", "localhost.example", "192.168.0.1", "128.0.0.1", "0.0.0.0", "::", "[::2]", "[::1", "127.0.0.1:5432"} {
		if IsLoopbackHost(host) {
			t.Errorf("remote or invalid host %q classified as loopback", host)
		}
	}
}

// postgresEnvKeys lists every variable NewConfigFromEnvironment reads.
var postgresEnvKeys = []string{
	"POSTGRES_USER",
	"POSTGRES_PASSWORD",
	"POSTGRES_HOST",
	"POSTGRES_PORT",
	"POSTGRES_DB",
}

// clearPostgresEnv empties every POSTGRES_* variable for one test, so the dev
// container environment cannot change the result. Empty values count as unset.
func clearPostgresEnv(t *testing.T) {
	t.Helper()
	for _, key := range postgresEnvKeys {
		t.Setenv(key, "")
	}
}

func TestConnectionString_escapesTheCredentials(t *testing.T) {
	config := &Config{
		User:     "us er",
		Password: "p@ss:word/1",
		Host:     "relational_db",
		Port:     "5432",
		Database: "onyx",
	}

	got := config.ConnectionString()

	want := "postgresql://us%20er:p%40ss%3Aword%2F1@relational_db:5432/onyx"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestPgDumpArgs_selectsTheFormat(t *testing.T) {
	config := &Config{User: "onyx", Database: "onyx_db"}

	tests := []struct {
		format string
		want   []string
	}{
		{format: "custom", want: []string{"-U", "onyx", "-d", "onyx_db", "-Fc"}},
		{format: "plain", want: []string{"-U", "onyx", "-d", "onyx_db", "-Fp"}},
		{format: "", want: []string{"-U", "onyx", "-d", "onyx_db", "-Fp"}},
	}
	for _, tt := range tests {
		if got := config.PgDumpArgs(tt.format); !slices.Equal(got, tt.want) {
			t.Errorf("PgDumpArgs(%q) = %v, want %v", tt.format, got, tt.want)
		}
	}
}

func TestNewConfigFromEnvironment(t *testing.T) {
	clearPostgresEnv(t)
	defaults := Config{User: DefaultUser, Password: DefaultPassword, Host: DefaultHost, Port: DefaultPort, Database: DefaultDatabase}
	tests := []struct {
		name string
		env  []string
		want Config
	}{
		{name: "defaults when unset", want: defaults},
		{
			name: "reads every variable",
			env:  []string{"POSTGRES_USER=onyx", "POSTGRES_PASSWORD=secret", "POSTGRES_HOST=relational_db", "POSTGRES_PORT=6543", "POSTGRES_DB=onyx_test"},
			want: Config{User: "onyx", Password: "secret", Host: "relational_db", Port: "6543", Database: "onyx_test"},
		},
		{
			name: "later values win and empty values are skipped",
			env:  []string{"POSTGRES_USER=file-user", "POSTGRES_PASSWORD=file-secret", "POSTGRES_PORT=25432", "POSTGRES_PASSWORD=", "POSTGRES_USER=shell-user", "MALFORMED"},
			want: Config{User: "shell-user", Password: "file-secret", Host: DefaultHost, Port: "25432", Database: DefaultDatabase},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := NewConfigFromEnvironment(tt.env); *got != tt.want {
				t.Fatalf("expected %+v, got %+v", tt.want, *got)
			}
		})
	}
	for _, key := range postgresEnvKeys {
		if os.Getenv(key) != "" {
			t.Fatalf("reading the private environment changed %s in the parent process", key)
		}
	}
}
