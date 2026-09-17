package coverage

import (
	"path/filepath"
	"testing"
)

func TestKind_baselinePathJoinsTheFile(t *testing.T) {
	dir := filepath.Join("repo", "web")

	if got, want := TypeScript.BaselinePath(dir), filepath.Join(dir, TypeBaselineFile); got != want {
		t.Fatalf("BaselinePath = %q, want %q", got, want)
	}
	if got, want := GoTests.BaselinePath(dir), filepath.Join(dir, BaselineFile); got != want {
		t.Fatalf("BaselinePath = %q, want %q", got, want)
	}
}

func TestKind_countPicksThePluralForm(t *testing.T) {
	cases := map[int]string{0: "0 directories", 1: "1 directory", 2: "2 directories"}
	for n, want := range cases {
		if got := TypeScript.Count(n); got != want {
			t.Errorf("Count(%d) = %q, want %q", n, got, want)
		}
	}
}

func TestKind_titleCapitalizesTheName(t *testing.T) {
	if got := TypeScript.Title(); got != "Type coverage" {
		t.Fatalf("Title = %q", got)
	}
	if got := (Kind{}).Title(); got != "" {
		t.Fatalf("Title of an unnamed kind = %q, want empty", got)
	}
}
