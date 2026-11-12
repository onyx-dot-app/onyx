package alembic

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

func TestMigrationsPending(t *testing.T) {
	for _, test := range []struct {
		name    string
		body    string
		pending bool
		wantErr bool
	}{
		{name: "head", body: "exit 0"},
		{name: "pending", body: "exit 10", pending: true},
		{name: "database error", body: "echo database-unreachable >&2; exit 1", wantErr: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			f := newFixture(t)
			python := devstack.PythonExecutable(f.root)
			writeScript(t, python, `printf '%s\n%s\n%s\n' "$PWD" "$POSTGRES_HOST" "$POSTGRES_PORT" > "$0.env"`+"\n"+test.body)
			pending, err := MigrationsPending(context.Background(), f.root, []string{"POSTGRES_HOST=localhost", "POSTGRES_PORT=15439"})
			if pending != test.pending || (err != nil) != test.wantErr {
				t.Fatalf("pending=%v err=%v", pending, err)
			}
			if test.wantErr && !strings.Contains(err.Error(), "database-unreachable") {
				t.Fatalf("missing diagnostic: %v", err)
			}
			data, err := os.ReadFile(python + ".env")
			if err != nil {
				t.Fatal(err)
			}
			backend, err := filepath.EvalSymlinks(filepath.Join(f.root, "backend"))
			if err != nil {
				t.Fatal(err)
			}
			if want := backend + "\nlocalhost\n15439\n"; string(data) != want {
				t.Fatalf("probe environment=%q want=%q", data, want)
			}
			args := strings.Join(calls(t, python), "\n")
			for _, want := range []string{"check_heads=True", "except DatabaseNotAtHead", "create_schema=false"} {
				if !strings.Contains(args, want) {
					t.Fatalf("probe missing %s", want)
				}
			}
		})
	}
}

func TestMigrationsPendingCancellation(t *testing.T) {
	f := newFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := MigrationsPending(ctx, f.root, nil); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancellation=%v", err)
	}
}
