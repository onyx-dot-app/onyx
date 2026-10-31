package typecoverage

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

func TestParse_readsFileCounts(t *testing.T) {
	files, err := Parse(strings.NewReader(`{"files":[
		{"file":"src/app/page.tsx","correct":9,"total":10},
		{"file":"next.config.ts","correct":0,"total":0}
	]}`))
	if err != nil {
		t.Fatalf("failed to parse: %v", err)
	}

	want := []FileCount{
		{File: "src/app/page.tsx", Correct: 9, Total: 10},
		{File: "next.config.ts", Correct: 0, Total: 0},
	}
	if len(files) != len(want) {
		t.Fatalf("expected %d files, got %d", len(want), len(files))
	}
	for i := range want {
		if files[i] != want[i] {
			t.Fatalf("expected %+v, got %+v", want[i], files[i])
		}
	}
}

func TestParse_rejectsMalformedInput(t *testing.T) {
	for name, input := range map[string]string{
		"not json":           `Generating route types...`,
		"no files":           `{"files":[]}`,
		"missing files key":  `{}`,
		"unknown field":      `{"files":[{"file":"a.ts","correct":1,"total":1,"extra":1}]}`,
		"empty path":         `{"files":[{"file":"","correct":1,"total":1}]}`,
		"more correct":       `{"files":[{"file":"a.ts","correct":2,"total":1}]}`,
		"negative count":     `{"files":[{"file":"a.ts","correct":-1,"total":1}]}`,
		"string count":       `{"files":[{"file":"a.ts","correct":"1","total":1}]}`,
		"truncated document": `{"files":[{"file":"a.ts"`,
		"extra data":         `{"files":[{"file":"a.ts","correct":1,"total":1}]} {"files":[]}`,
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := Parse(strings.NewReader(input)); err == nil {
				t.Fatalf("expected an error for %s", input)
			}
		})
	}
}

func TestAggregate_groupsByDirectoryDepth(t *testing.T) {
	profile := Aggregate([]FileCount{
		{File: "src/app/admin/users/page.tsx", Correct: 3, Total: 4},
		{File: "src/app/admin/layout.tsx", Correct: 1, Total: 1},
		{File: "src/app/page.tsx", Correct: 5, Total: 10},
		{File: "src/lib/utils.ts", Correct: 2, Total: 2},
		{File: "next.config.ts", Correct: 1, Total: 2},
		{File: "tests/setup.ts", Correct: 0, Total: 0},
	}, 3)

	want := []coverage.PackageCoverage{
		{Package: ".", Covered: 1, Total: 2},
		{Package: "src/app", Covered: 5, Total: 10},
		{Package: "src/app/admin", Covered: 4, Total: 5},
		{Package: "src/lib", Covered: 2, Total: 2},
		{Package: "tests", Covered: 0, Total: 0},
	}
	if len(profile.Packages) != len(want) {
		t.Fatalf("expected %d rows, got %+v", len(want), profile.Packages)
	}
	for i := range want {
		if profile.Packages[i] != want[i] {
			t.Fatalf("row %d: expected %+v, got %+v", i, want[i], profile.Packages[i])
		}
	}
}

// A directory with no identifiers must not read as a regression.
func TestAggregate_emptyDirectoryIsFullyCovered(t *testing.T) {
	profile := Aggregate([]FileCount{{File: "types/empty.d.ts", Correct: 0, Total: 0}}, Depth)

	if got := profile.Packages[0].Percent(); got != 100 {
		t.Fatalf("expected 100%%, got %v", got)
	}
}
