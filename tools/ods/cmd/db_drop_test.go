package cmd

import (
	"strings"
	"testing"
)

func TestRunDBDrop_recreatesTheDatabaseFromTemplate1(t *testing.T) {
	binDir := dbSetup(t)
	t.Setenv("POSTGRES_USER", "alice")
	t.Setenv("POSTGRES_PASSWORD", "s3cret")
	t.Setenv("POSTGRES_DB", "onyx_test")
	container, calls := dbFakeDocker(t, binDir, "")

	if err := runDBDrop(&DBDropOptions{Yes: true}); err != nil {
		t.Fatalf("runDBDrop failed: %v", err)
	}

	psql := func(sql string) []string {
		return []string{"exec", "-i", "-e", "PGPASSWORD=s3cret", container, "psql", "-U", "alice", "-d", "template1", "-c", sql}
	}
	dbAssertCalls(t, dbDockerExecs(calls()), [][]string{
		psql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'onyx_test' AND pid <> pg_backend_pid();"),
		psql("DROP DATABASE IF EXISTS onyx_test;"),
		psql("CREATE DATABASE onyx_test;"),
	})
}

func TestRunDBDrop_continuesWhenTerminatingConnectionsFails(t *testing.T) {
	binDir := dbSetup(t)
	_, calls := dbFakeDocker(t, binDir, `case "$*" in *pg_terminate_backend*) exit 1;; esac`)
	logs := dbCaptureLog(t)

	if err := runDBDrop(&DBDropOptions{Yes: true}); err != nil {
		t.Fatalf("runDBDrop failed: %v", err)
	}

	execs := dbDockerExecs(calls())
	if len(execs) != 3 {
		t.Fatalf("expected terminate, drop and create, got:\n%s", dbFormatCalls(execs))
	}
	if !strings.Contains(logs.String(), "Failed to terminate connections (this may be okay)") {
		t.Fatalf("expected a warning about the connections, got %q", logs.String())
	}
}

func TestRunDBDrop_recreatesOnlyTheSchema(t *testing.T) {
	binDir := dbSetup(t)
	container, calls := dbFakeDocker(t, binDir, "")

	if err := runDBDrop(&DBDropOptions{Yes: true, Schema: "tenant_abc"}); err != nil {
		t.Fatalf("runDBDrop failed: %v", err)
	}

	psql := func(sql string) []string {
		return []string{"exec", "-i", "-e", "PGPASSWORD=password", container, "psql", "-U", "postgres", "-d", "postgres", "-c", sql}
	}
	dbAssertCalls(t, dbDockerExecs(calls()), [][]string{
		psql("DROP SCHEMA IF EXISTS tenant_abc CASCADE;"),
		psql("CREATE SCHEMA tenant_abc;"),
	})
}

func TestRunDBDrop_rejectsUnsafeIdentifiersBeforeRunningSQL(t *testing.T) {
	cases := []struct {
		name     string
		schema   string
		database string
		wantErr  string
	}{
		{"schema", "public; DROP TABLE users", "", "Invalid schema name: public; DROP TABLE users"},
		{"database", "", "onyx-prod", "Invalid database name: onyx-prod"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := dbSetup(t)
			t.Setenv("POSTGRES_DB", c.database)
			_, calls := dbFakeDocker(t, binDir, "")

			err := runDBDrop(&DBDropOptions{Yes: true, Schema: c.schema})

			if err == nil || err.Error() != c.wantErr {
				t.Fatalf("expected %q, got %v", c.wantErr, err)
			}
			if execs := dbDockerExecs(calls()); len(execs) != 0 {
				t.Fatalf("expected no SQL to run, got:\n%s", dbFormatCalls(execs))
			}
		})
	}
}

func TestRunDBDrop_stopsAtTheFirstFailedStatement(t *testing.T) {
	cases := []struct {
		name      string
		schema    string
		failOn    string
		wantErr   string
		wantExecs int
	}{
		{"drop database", "", "DROP DATABASE", "Failed to drop database: exit status 3", 2},
		{"create database", "", "CREATE DATABASE", "Failed to create database: exit status 3", 3},
		{"drop schema", "tenant", "DROP SCHEMA", "Failed to drop schema: exit status 3", 1},
		{"create schema", "tenant", "CREATE SCHEMA", "Failed to create schema: exit status 3", 2},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			binDir := dbSetup(t)
			_, calls := dbFakeDocker(t, binDir, `case "$*" in *"`+c.failOn+`"*) exit 3;; esac`)

			err := runDBDrop(&DBDropOptions{Yes: true, Schema: c.schema})

			if err == nil || err.Error() != c.wantErr {
				t.Fatalf("expected %q, got %v", c.wantErr, err)
			}
			if execs := dbDockerExecs(calls()); len(execs) != c.wantExecs {
				t.Fatalf("expected %d statements, got:\n%s", c.wantExecs, dbFormatCalls(execs))
			}
		})
	}
}
