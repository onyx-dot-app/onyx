package cmd

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"
)

func TestRunCheckGetattr_reportsTheViolationCount(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "backend", "onyx", "a.py"), "x = getattr(o, n)\ny = getattr(o, m)\n")
	writeFile(t, filepath.Join(root, "backend", "onyx", "b.py"), "z = o.name\n")

	var stderr bytes.Buffer
	clean, err := runCheckGetattr(nil, false, &stderr)
	if err != nil {
		t.Fatalf("runCheckGetattr: %v", err)
	}

	if clean {
		t.Fatal("expected violations")
	}
	if got, want := stderr.String(), "\nFound 2 getattr reference(s) in 1 file(s).\n"; got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestRunCheckGetattr_passesCleanFiles(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "backend", "onyx", "a.py"), "x = getattr(o, n)  # ods: ignore[getattr] Dynamic.\n")

	var stderr bytes.Buffer
	clean, err := runCheckGetattr([]string{"onyx"}, false, &stderr)
	if err != nil {
		t.Fatalf("runCheckGetattr: %v", err)
	}
	if !clean || stderr.Len() != 0 {
		t.Fatalf("expected a clean run, got clean=%v stderr=%q", clean, stderr.String())
	}
}

func TestRunCheckGetattr_annotate(t *testing.T) {
	t.Run("marks violations so the check passes", func(t *testing.T) {
		root := devtoolRepo(t)
		file := filepath.Join(root, "backend", "onyx", "a.py")
		writeFile(t, file, "x = getattr(o, n)\n")

		var stderr bytes.Buffer
		clean, err := runCheckGetattr(nil, true, &stderr)
		if err != nil {
			t.Fatalf("runCheckGetattr: %v", err)
		}
		if !clean || stderr.Len() != 0 {
			t.Fatalf("expected a clean annotate run, got clean=%v stderr=%q", clean, stderr.String())
		}
		if got, want := devtoolReadFile(t, file), "x = getattr(o, n)  # ods: ignore[getattr]\n"; got != want {
			t.Fatalf("expected %q, got %q", want, got)
		}
		if clean, err := runCheckGetattr(nil, false, &stderr); err != nil || !clean {
			t.Fatalf("expected the check to pass after annotating, got clean=%v err=%v", clean, err)
		}
	})

	t.Run("fails when a line needs a manual marker", func(t *testing.T) {
		root := devtoolRepo(t)
		// A trailing comment here would land inside the string literal.
		content := "s = f\"\"\"{getattr(o, n)}\nrest\"\"\"\n"
		file := filepath.Join(root, "backend", "onyx", "a.py")
		writeFile(t, file, content)

		var stderr bytes.Buffer
		clean, err := runCheckGetattr(nil, true, &stderr)
		if err != nil {
			t.Fatalf("runCheckGetattr: %v", err)
		}
		if clean {
			t.Fatal("expected the run to fail")
		}
		if got, want := stderr.String(), "\nSome lines need a manual 'ods: ignore[getattr]' marker.\n"; got != want {
			t.Fatalf("expected %q, got %q", want, got)
		}
		if got := devtoolReadFile(t, file); got != content {
			t.Fatalf("expected the file to be left alone, got %q", got)
		}
	})
}

func TestRunCheckGetattr_rejectsPathsOutsideTheBackend(t *testing.T) {
	cases := []struct {
		annotate bool
		want     string
	}{
		{false, "Error checking getattr references: "},
		{true, "Error annotating getattr references: "},
	}
	for _, c := range cases {
		root := devtoolRepo(t)
		writeFile(t, filepath.Join(root, "scripts", "a.py"), "x = getattr(o, n)\n")

		_, err := runCheckGetattr([]string{filepath.Join(root, "scripts", "a.py")}, c.annotate, &bytes.Buffer{})
		if err == nil || !strings.HasPrefix(err.Error(), c.want) {
			t.Fatalf("expected an error starting with %q, got %v", c.want, err)
		}
	}
}
