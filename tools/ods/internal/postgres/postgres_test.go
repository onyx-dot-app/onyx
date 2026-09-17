package postgres

import (
	"slices"
	"testing"
)

// postgresEnvKeys lists every variable NewConfigFromEnv reads.
var postgresEnvKeys = []string{
	"POSTGRES_USER",
	"POSTGRES_PASSWORD",
	"POSTGRES_HOST",
	"POSTGRES_PORT",
	"POSTGRES_DB",
}

// clearPostgresEnv empties every POSTGRES_* variable for one test, so the dev
// container environment cannot change the result. getEnvOrDefault treats an
// empty value as unset.
func clearPostgresEnv(t *testing.T) {
	t.Helper()
	for _, key := range postgresEnvKeys {
		t.Setenv(key, "")
	}
}

func TestNewConfigFromEnv_usesDefaultsWhenUnset(t *testing.T) {
	clearPostgresEnv(t)

	config := NewConfigFromEnv()

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

func TestNewConfigFromEnv_readsTheEnvironment(t *testing.T) {
	clearPostgresEnv(t)
	t.Setenv("POSTGRES_USER", "onyx")
	t.Setenv("POSTGRES_PASSWORD", "secret")
	t.Setenv("POSTGRES_HOST", "relational_db")
	t.Setenv("POSTGRES_PORT", "6543")
	t.Setenv("POSTGRES_DB", "onyx_test")

	config := NewConfigFromEnv()

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
