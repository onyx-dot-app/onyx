package auditcmd

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

const existingAllowlist = `{"ignores":[{"id":"GHSA-zzzz","reason":"dev only"}]}`

func readAllowlist(t *testing.T, path string) []audit.IgnoreEntry {
	t.Helper()
	entries, err := audit.FetchIgnores(path)
	if err != nil {
		t.Fatalf("read allowlist: %v", err)
	}
	return entries
}

func TestRunAuditIgnoreAdd_appendsAndSaves(t *testing.T) {
	root := chdirNewRepo(t)
	gittest.Git(t, root, "config", "user.email", "dev@example.com")
	path := writeFixture(t, t.TempDir(), "ignores.json", existingAllowlist)

	var out bytes.Buffer
	err := runAuditIgnoreAdd(" CVE-2026-0001 ", path, &AuditIgnoreAddOptions{
		Ecosystem: " npm ",
		Reason:    " not reachable ",
		Expires:   "2026-12-31",
		Yes:       true,
	}, &out)
	if err != nil {
		t.Fatalf("runAuditIgnoreAdd: %v", err)
	}

	want := []audit.IgnoreEntry{
		{ID: "CVE-2026-0001", Ecosystem: "npm", Reason: "not reachable", AddedBy: "dev@example.com", Expires: "2026-12-31"},
		{ID: "GHSA-zzzz", Reason: "dev only"},
	}
	if got := readAllowlist(t, path); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected the saved allowlist %+v, got %+v", want, got)
	}
	wantOut := "Changes:\n" +
		"  + CVE-2026-0001  eco=npm  expires=2026-12-31  by=dev@example.com  reason=not reachable\n" +
		"Uploaded 2 entries to " + path + "\n"
	if out.String() != wantOut {
		t.Fatalf("expected output %q, got %q", wantOut, out.String())
	}
}

func TestRunAuditIgnoreAdd_explicitAddedByWithoutGitEmail(t *testing.T) {
	chdirNewRepo(t)
	path := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[]}`)

	opts := &AuditIgnoreAddOptions{Reason: "accepted", Yes: true}
	if err := runAuditIgnoreAdd("GHSA-aaaa", path, opts, &bytes.Buffer{}); err != nil {
		t.Fatalf("runAuditIgnoreAdd: %v", err)
	}
	opts.AddedBy = "release-bot"
	if err := runAuditIgnoreAdd("GHSA-bbbb", path, opts, &bytes.Buffer{}); err != nil {
		t.Fatalf("runAuditIgnoreAdd: %v", err)
	}

	want := []audit.IgnoreEntry{
		{ID: "GHSA-aaaa", Reason: "accepted"},
		{ID: "GHSA-bbbb", Reason: "accepted", AddedBy: "release-bot"},
	}
	if got := readAllowlist(t, path); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected %+v, got %+v", want, got)
	}
}

func TestRunAuditIgnoreAdd_rejections(t *testing.T) {
	cases := []struct {
		name string
		id   string
		opts AuditIgnoreAddOptions
		file string // allowlist content; empty means no file
		want string
	}{
		{
			name: "blank reason",
			id:   "GHSA-aaaa",
			opts: AuditIgnoreAddOptions{Reason: "   "},
			file: existingAllowlist,
			want: "A --reason is required to suppress an advisory",
		},
		{
			name: "blank id",
			id:   " ",
			opts: AuditIgnoreAddOptions{Reason: "accepted"},
			file: existingAllowlist,
			want: "Invalid suppression: id is required",
		},
		{
			name: "malformed expiry",
			id:   "GHSA-aaaa",
			opts: AuditIgnoreAddOptions{Reason: "accepted", Expires: "31/12/2026"},
			file: existingAllowlist,
			want: "Invalid suppression: must be YYYY-MM-DD",
		},
		{
			name: "missing allowlist",
			id:   "GHSA-aaaa",
			opts: AuditIgnoreAddOptions{Reason: "accepted"},
			want: "Failed to fetch allowlist from ",
		},
		{
			name: "existing entry",
			id:   "ghsa-zzzz",
			opts: AuditIgnoreAddOptions{Reason: "accepted"},
			file: existingAllowlist,
			want: "An allowlist entry for ghsa-zzzz already exists; update it with `ods audit ignore edit`",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			chdirNewRepo(t)
			path := filepath.Join(t.TempDir(), "ignores.json")
			if tc.file != "" {
				writeFixture(t, filepath.Dir(path), filepath.Base(path), tc.file)
			}
			tc.opts.Yes = true

			var out bytes.Buffer
			err := runAuditIgnoreAdd(tc.id, path, &tc.opts, &out)
			requireCommandError(t, err, tc.want)

			if tc.file == "" {
				if _, statErr := os.Stat(path); !os.IsNotExist(statErr) {
					t.Fatalf("expected no allowlist to be created, stat returned %v", statErr)
				}
			} else if data, readErr := os.ReadFile(path); readErr != nil || string(data) != tc.file {
				t.Fatalf("expected the allowlist to be unchanged, got %q (%v)", data, readErr)
			}
			if out.Len() != 0 {
				t.Fatalf("expected no output, got %q", out.String())
			}
		})
	}
}

func TestAuditIgnoreCommand_addUsesTheSharedIgnoreURL(t *testing.T) {
	chdirNewRepo(t)
	path := writeFixture(t, t.TempDir(), "ignores.json", existingAllowlist)

	cmd := newAuditIgnoreCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetArgs([]string{"--ignore-url", path, "add", "GHSA-aaaa", "--reason", "accepted", "--added-by", "ci", "--yes"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}

	want := []audit.IgnoreEntry{
		{ID: "GHSA-aaaa", Reason: "accepted", AddedBy: "ci"},
		{ID: "GHSA-zzzz", Reason: "dev only"},
	}
	if got := readAllowlist(t, path); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected %+v, got %+v", want, got)
	}
	if !strings.HasSuffix(out.String(), "Uploaded 2 entries to "+path+"\n") {
		t.Fatalf("expected the upload summary on the command output, got %q", out.String())
	}
}

// requireNoTerminal skips when /dev/tty opens, because the editor would then
// take over the terminal instead of falling back.
func requireNoTerminal(t *testing.T) {
	t.Helper()
	if tty, err := os.Open("/dev/tty"); err == nil {
		_ = tty.Close()
		t.Skip("an interactive terminal is available")
	}
}

func TestRunAuditEdit_withoutTerminalPrintsTheAllowlist(t *testing.T) {
	requireNoTerminal(t)
	chdirNewRepo(t)

	cases := []struct {
		name    string
		content string // empty means no file
		want    string
	}{
		{
			name:    "existing entries",
			content: `{"ignores":[{"id":"GHSA-zzzz","ecosystem":"npm","reason":"dev only","added_by":"dev@example.com","expires":"2027-01-01"},{"id":"CVE-2026-0001"}]}`,
			want:    "Allowlist (2 entries):\n  - GHSA-zzzz  eco=npm  expires=2027-01-01  by=dev@example.com  reason=dev only\n  - CVE-2026-0001\n",
		},
		{
			name: "missing local file",
			want: "Allowlist is empty.\n",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "ignores.json")
			if tc.content != "" {
				writeFixture(t, filepath.Dir(path), filepath.Base(path), tc.content)
			}

			var out bytes.Buffer
			if err := runAuditEdit(path, &out); err != nil {
				t.Fatalf("runAuditEdit: %v", err)
			}
			if out.String() != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, out.String())
			}

			if tc.content == "" {
				if _, err := os.Stat(path); !os.IsNotExist(err) {
					t.Fatalf("expected no allowlist to be created, stat returned %v", err)
				}
			} else if data, err := os.ReadFile(path); err != nil || string(data) != tc.content {
				t.Fatalf("expected the allowlist to be unchanged, got %q (%v)", data, err)
			}
		})
	}
}

func TestAuditIgnoreCommand_bareAndEditOpenTheEditor(t *testing.T) {
	requireNoTerminal(t)
	chdirNewRepo(t)
	path := writeFixture(t, t.TempDir(), "ignores.json", existingAllowlist)

	for _, args := range [][]string{
		{"--ignore-url", path},
		{"edit", "--ignore-url", path},
	} {
		t.Run(strings.Join(args[:len(args)-1], " "), func(t *testing.T) {
			cmd := newAuditIgnoreCommand()
			var out bytes.Buffer
			cmd.SetOut(&out)
			cmd.SetArgs(args)
			if err := cmd.Execute(); err != nil {
				t.Fatalf("Execute: %v", err)
			}
			if want := "Allowlist (1 entries):\n  - GHSA-zzzz  reason=dev only\n"; out.String() != want {
				t.Fatalf("expected %q, got %q", want, out.String())
			}
		})
	}
}

func TestRunAuditEdit_fetchFailure(t *testing.T) {
	path := writeFixture(t, t.TempDir(), "ignores.json", "{broken")
	err := runAuditEdit(path, &bytes.Buffer{})
	requireCommandError(t, err, "Failed to fetch allowlist from "+path+": failed to parse allowlist")
}

func TestPrintDiff(t *testing.T) {
	var out bytes.Buffer
	printDiff(&out,
		[]audit.IgnoreEntry{{ID: "GHSA-new", Reason: "accepted"}},
		[]audit.IgnoreEntry{{ID: "GHSA-old", Ecosystem: "PyPI"}},
		[]audit.IgnoreEntry{{ID: "GHSA-kept", Expires: "2027-01-01"}},
	)
	want := "Changes:\n  + GHSA-new  reason=accepted\n  - GHSA-old  eco=PyPI\n  ~ GHSA-kept  expires=2027-01-01\n"
	if out.String() != want {
		t.Fatalf("expected %q, got %q", want, out.String())
	}
}

// TestEditorRowsRoundTrip pins that the editor's columns, the rows built from
// entries, and the entries read back from rows all use the same keys.
func TestEditorRowsRoundTrip(t *testing.T) {
	entry := audit.IgnoreEntry{ID: "GHSA-x", Ecosystem: "npm", Reason: "r", AddedBy: "a", Expires: "2027-01-01"}
	row := entryToRow(entry)

	cols := ignoreColumns("dev@example.com")
	if len(cols) != len(row) {
		t.Fatalf("expected one column per row field, got %d columns for %v", len(cols), row)
	}
	for _, c := range cols {
		if _, ok := row[c.Key]; !ok {
			t.Fatalf("column %q has no row field", c.Key)
		}
		if c.Key == "added_by" && c.Default != "dev@example.com" {
			t.Fatalf("expected Added By to default to the git email, got %q", c.Default)
		}
		if c.Key == "expires" && (c.Validate == nil || c.Validate("tomorrow") == nil) {
			t.Fatal("expected the expires column to reject a non-date")
		}
	}
	if got := rowToEntry(row); got != entry {
		t.Fatalf("expected %+v after the round trip, got %+v", entry, got)
	}
}
