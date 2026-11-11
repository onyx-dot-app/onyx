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

func TestNewConfigFromEnvironment_usesDefaultsWhenUnset(t *testing.T) {
	config := NewConfigFromEnvironment(nil)

	want := Config{
		User:     DefaultUser,
		Password: DefaultPassword,
		Host:     DefaultHost,
		Port:     DefaultPort,
		Database: DefaultDatabase,
	}
	if *config != want {
		t.Fatalf("expected %+v, got %+v", want, *config)
	}
}

func TestNewConfigFromEnvironment_readsTheEnvironment(t *testing.T) {
	config := NewConfigFromEnvironment([]string{
		"POSTGRES_USER=onyx",
		"POSTGRES_PASSWORD=secret",
		"POSTGRES_HOST=relational_db",
		"POSTGRES_PORT=6543",
		"POSTGRES_DB=onyx_test",
	})

	want := Config{
		User:     "onyx",
		Password: "secret",
		Host:     "relational_db",
		Port:     "6543",
		Database: "onyx_test",
	}
	if *config != want {
		t.Fatalf("expected %+v, got %+v", want, *config)
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

func TestClientArgs_targetTheUserAndDatabase(t *testing.T) {
	config := &Config{User: "onyx", Database: "onyx_db"}

	want := []string{"-U", "onyx", "-d", "onyx_db"}
	if got := config.PgRestoreArgs(); !slices.Equal(got, want) {
		t.Errorf("PgRestoreArgs() = %v, want %v", got, want)
	}
	if got := config.PsqlArgs(); !slices.Equal(got, want) {
		t.Errorf("PsqlArgs() = %v, want %v", got, want)
	}
}

func TestEnv_carriesThePassword(t *testing.T) {
	config := &Config{Password: "secret"}

	env := config.Env()

	if len(env) != 1 || env["PGPASSWORD"] != "secret" {
		t.Fatalf("expected a single PGPASSWORD entry, got %v", env)
	}
}

func TestNewConfigFromEnvironmentKeepsPrivateFileDefaultsAndShellOverrides(t *testing.T) {
	clearPostgresEnv(t)
	config := NewConfigFromEnvironment([]string{
		"POSTGRES_USER=file-user", "POSTGRES_PASSWORD=file-secret", "POSTGRES_PORT=25432",
		"POSTGRES_PASSWORD=", "POSTGRES_USER=shell-user",
	})
	if config.User != "shell-user" || config.Password != "file-secret" || config.Port != "25432" {
		t.Fatal("private environment precedence was lost")
	}
	if os.Getenv("POSTGRES_USER") != "" || os.Getenv("POSTGRES_PASSWORD") != "" {
		t.Fatal("private configuration changed the parent process")
	}
}
