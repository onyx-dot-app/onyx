package pycheck

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// getattrRule is the rule under test throughout this file.
var getattrRule = NewBannedName("getattr")

// lineNums extracts the line numbers from violation lines.
func lineNums(violations []ViolationLine) []int {
	nums := make([]int, len(violations))
	for i, v := range violations {
		nums[i] = v.LineNum
	}
	return nums
}

// assertLineNums fails the test unless the violations are exactly at want.
func assertLineNums(t *testing.T, violations []ViolationLine, want []int) {
	t.Helper()
	got := lineNums(violations)
	if len(got) != len(want) {
		t.Fatalf("Expected violations at lines %v, got %v", want, got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("Expected violations at lines %v, got %v", want, got)
		}
	}
}

// createTempPythonFile creates a temporary Python file with given content.
func createTempPythonFile(t *testing.T, content string) string {
	t.Helper()
	f, err := os.CreateTemp(t.TempDir(), "test_*.py")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	if _, err := f.WriteString(content); err != nil {
		_ = f.Close()
		t.Fatalf("Failed to write temp file: %v", err)
	}
	if err := f.Close(); err != nil {
		t.Fatalf("Failed to close temp file: %v", err)
	}
	return f.Name()
}

func TestCheckContentFlagsReferences(t *testing.T) {
	// Precondition.
	tests := []struct {
		name    string
		content string
		want    []int
	}{
		{
			name:    "plain call",
			content: `value = getattr(obj, name)`,
			want:    []int{1},
		},
		{
			name:    "call with space before paren",
			content: `value = getattr (obj, name)`,
			want:    []int{1},
		},
		{
			name:    "bare alias reference",
			content: `lookup = getattr`,
			want:    []int{1},
		},
		{
			name:    "reference at line start",
			content: `getattr(obj, name)`,
			want:    []int{1},
		},
		{
			name:    "passed as argument",
			content: `value = reduce(getattr, path.split("."), obj)`,
			want:    []int{1},
		},
		{
			name:    "several references on one line count once",
			content: `pair = (getattr(a, x), getattr(b, y))`,
			want:    []int{1},
		},
		{
			name: "line numbers are one-based per line",
			content: `import os

value = getattr(obj, name)
other = 1
lookup = getattr`,
			want: []int{3, 5},
		},
	}

	// Under test and postcondition.
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assertLineNums(t, CheckContent(tt.content, getattrRule), tt.want)
		})
	}
}

func TestCheckContentSkipsOtherIdentifiers(t *testing.T) {
	// Precondition.
	tests := []struct {
		name    string
		content string
	}{
		{name: "attribute access", content: `value = obj.getattr(name)`},
		{name: "attribute access with spaces", content: `value = obj .  getattr(name)`},
		{name: "dunder definition", content: `    def __getattr__(self, name: str) -> object:`},
		{name: "dunder getattribute", content: `        return object.__getattribute__(self, name)`},
		{name: "prefixed identifier", content: `my_getattr(obj, name)`},
		{name: "suffixed identifier", content: `getattr_helper(obj, name)`},
	}

	// Under test and postcondition.
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assertLineNums(t, CheckContent(tt.content, getattrRule), nil)
		})
	}
}

func TestCheckContentSkipsStringsAndComments(t *testing.T) {
	// Precondition.
	tests := []struct {
		name    string
		content string
		want    []int
	}{
		{
			name:    "full-line comment",
			content: `# getattr(obj, name) is banned here`,
			want:    nil,
		},
		{
			name:    "trailing comment mention",
			content: `value = 1  # replaces the old getattr(obj, name) lookup`,
			want:    nil,
		},
		{
			name:    "single-quoted string",
			content: `message = "do not use getattr(obj, name)"`,
			want:    nil,
		},
		{
			name:    "string with escaped quotes",
			content: `message = "she said \"getattr(obj, name)\" out loud"`,
			want:    nil,
		},
		{
			name:    "raw string with backslashes",
			content: `pattern = r"\bgetattr\("`,
			want:    nil,
		},
		{
			name:    "byte string",
			content: `payload = b'getattr(obj, name)'`,
			want:    nil,
		},
		{
			name: "triple-quoted block spanning lines",
			content: `def f() -> None:
    """Explains getattr(obj, name).

    More getattr( talk here.
    """
    return getattr(obj, name)`,
			want: []int{6},
		},
		{
			name:    "code after a closing triple quote on the same line",
			content: `value = """getattr( in string""" + str(getattr(obj, name))`,
			want:    []int{1},
		},
		{
			name: "single-quoted string continued with a trailing backslash",
			content: `text = "leading getattr( \
still getattr( inside the string"
value = getattr(obj, name)`,
			want: []int{3},
		},
		{
			name:    "hash inside a string does not start a comment",
			content: `value = getattr(obj, "#name")`,
			want:    []int{1},
		},
	}

	// Under test and postcondition.
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assertLineNums(t, CheckContent(tt.content, getattrRule), tt.want)
		})
	}
}

func TestCheckContentFStringFields(t *testing.T) {
	// Precondition.
	// Replacement fields inside f-strings are code; the literal parts are not.
	tests := []struct {
		name    string
		content string
		want    []int
	}{
		{
			name:    "call inside a replacement field",
			content: `label = f"{getattr(obj, name)}"`,
			want:    []int{1},
		},
		{
			name:    "raw f-string replacement field",
			content: `label = rf"{getattr(obj, name)}\d"`,
			want:    []int{1},
		},
		{
			name:    "literal text is not code",
			content: `label = f"use getattr( wisely"`,
			want:    nil,
		},
		{
			name:    "escaped braces stay literal",
			content: `label = f"{{getattr(obj, name)}}"`,
			want:    nil,
		},
		{
			name:    "nested string inside a field is not code",
			content: `label = f"{d['getattr']}"`,
			want:    nil,
		},
		{
			name:    "nested string reusing the outer quote is not code",
			content: `label = f"{d["getattr"]}"`,
			want:    nil,
		},
		{
			name: "format spec braces do not derail the scan",
			content: `label = f"{value:{width}}"
value = getattr(obj, name)`,
			want: []int{2},
		},
		{
			name: "field spanning lines in a triple-quoted f-string",
			content: `label = f"""prefix {
    getattr(obj, name)
} suffix"""`,
			want: []int{2},
		},
		{
			name:    "plain string is still fully literal",
			content: `label = "{getattr(obj, name)}"`,
			want:    nil,
		},
	}

	// Under test and postcondition.
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assertLineNums(t, CheckContent(tt.content, getattrRule), tt.want)
		})
	}
}

func TestCheckContentUnicodeIdentifierBoundaries(t *testing.T) {
	// Precondition.
	// A non-ASCII letter adjacent to the name makes it a longer identifier.
	tests := []struct {
		name    string
		content string
		want    []int
	}{
		{name: "unicode suffix", content: `getattrñ(obj, name)`, want: nil},
		{name: "unicode prefix", content: `ñgetattr = 1`, want: nil},
		{name: "plain reference still flagged", content: `value = getattr(obj, name)`, want: []int{1}},
	}

	// Under test and postcondition.
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assertLineNums(t, CheckContent(tt.content, getattrRule), tt.want)
		})
	}
}

func TestCheckContentIgnoreMarker(t *testing.T) {
	// Precondition.
	tests := []struct {
		name    string
		content string
		want    []int
	}{
		{
			name:    "marker suppresses the line",
			content: `value = getattr(obj, name)  # ods: ignore[getattr]`,
			want:    nil,
		},
		{
			name:    "marker with justification prose",
			content: `value = getattr(obj, name)  # ods: ignore[getattr] Dynamic Pydantic field lookup.`,
			want:    nil,
		},
		{
			name:    "marker after an existing comment",
			content: `value = getattr(obj, name)  # Legacy path.  # ods: ignore[getattr]`,
			want:    nil,
		},
		{
			name:    "marker lists several rules",
			content: `value = getattr(obj, name)  # ods: ignore[setattr, getattr]`,
			want:    nil,
		},
		{
			name:    "marker for another rule does not suppress",
			content: `value = getattr(obj, name)  # ods: ignore[setattr]`,
			want:    []int{1},
		},
		{
			name: "marker on a neighboring line does not suppress",
			content: `# ods: ignore[getattr]
value = getattr(obj, name)`,
			want: []int{2},
		},
		{
			name:    "marker inside a string does not suppress",
			content: `value = getattr(obj, "ods: ignore[getattr]")`,
			want:    []int{1},
		},
		{
			name:    "marker works when a hash appears inside a string",
			content: `value = getattr(obj, "#name")  # ods: ignore[getattr]`,
			want:    nil,
		},
	}

	// Under test and postcondition.
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assertLineNums(t, CheckContent(tt.content, getattrRule), tt.want)
		})
	}
}

func TestAnnotateFileAppendsMarkers(t *testing.T) {
	// Precondition.
	content := `import os

value = getattr(obj, name)
other = obj.getattr(name)
allowed = getattr(obj, name)  # ods: ignore[getattr] Justified.
text = "getattr(obj, name)"
`
	path := createTempPythonFile(t, content)
	marker := "  # ods: ignore[getattr]"

	// Under test.
	annotated, manual, err := annotateFile(path, getattrRule, marker)

	// Postcondition.
	if err != nil {
		t.Fatalf("annotateFile failed: %v", err)
	}
	if annotated != 1 || len(manual) != 0 {
		t.Fatalf("Expected 1 annotated line and no manual lines, got %d and %v", annotated, manual)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to read annotated file: %v", err)
	}
	got := strings.Split(string(data), "\n")[2]
	want := `value = getattr(obj, name)  # ods: ignore[getattr]`
	if got != want {
		t.Fatalf("Expected annotated line %q, got %q", want, got)
	}
	if len(CheckContent(string(data), getattrRule)) != 0 {
		t.Fatalf("Expected the annotated file to be violation-free")
	}
}

func TestAnnotateFileIsIdempotent(t *testing.T) {
	// Precondition.
	path := createTempPythonFile(t, "value = getattr(obj, name)\n")
	marker := "  # ods: ignore[getattr]"
	if _, _, err := annotateFile(path, getattrRule, marker); err != nil {
		t.Fatalf("First annotateFile failed: %v", err)
	}
	first, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to read file: %v", err)
	}

	// Under test.
	annotated, manual, err := annotateFile(path, getattrRule, marker)

	// Postcondition.
	if err != nil {
		t.Fatalf("Second annotateFile failed: %v", err)
	}
	if annotated != 0 || len(manual) != 0 {
		t.Fatalf("Expected a no-op second run, got %d annotated and %v manual", annotated, manual)
	}
	second, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to read file: %v", err)
	}
	if string(first) != string(second) {
		t.Fatalf("Expected the file to be unchanged by the second run")
	}
}

func TestAnnotateFileReportsUnsafeLines(t *testing.T) {
	// Precondition.
	// Both violations sit on lines where a trailing comment would change the
	// code: a backslash continuation and an open string.
	content := `value = getattr(obj, name) or \
    fallback
text = getattr(obj, name), """open string
closes here"""
`
	path := createTempPythonFile(t, content)

	// Under test.
	annotated, manual, err := annotateFile(path, getattrRule, "  # ods: ignore[getattr]")

	// Postcondition.
	if err != nil {
		t.Fatalf("annotateFile failed: %v", err)
	}
	if annotated != 0 {
		t.Fatalf("Expected no mechanical annotations, got %d", annotated)
	}
	assertLineNums(t, manual, []int{1, 3})
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to read file: %v", err)
	}
	if string(data) != content {
		t.Fatalf("Expected the file to be unchanged")
	}
}

func TestAnnotateFilePreservesCRLF(t *testing.T) {
	// Precondition.
	// Line 3 is a backslash continuation, so it needs a manual marker even on a
	// CRLF file.
	content := "value = getattr(obj, name)\r\nother = 1\r\ncontinued = getattr(obj, name) or \\\r\n    fallback\r\n"
	path := createTempPythonFile(t, content)

	// Under test.
	annotated, manual, err := annotateFile(path, getattrRule, "  # ods: ignore[getattr]")

	// Postcondition.
	if err != nil {
		t.Fatalf("annotateFile failed: %v", err)
	}
	if annotated != 1 {
		t.Fatalf("Expected 1 annotated line, got %d", annotated)
	}
	assertLineNums(t, manual, []int{3})
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to read file: %v", err)
	}
	want := "value = getattr(obj, name)  # ods: ignore[getattr]\r\nother = 1\r\ncontinued = getattr(obj, name) or \\\r\n    fallback\r\n"
	if string(data) != want {
		t.Fatalf("Expected %q, got %q", want, string(data))
	}
}

// writePythonFile creates path (and parent directories) with dummy content.
func writePythonFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("Failed to create directory: %v", err)
	}
	if err := os.WriteFile(path, []byte("x = 1\n"), 0o644); err != nil {
		t.Fatalf("Failed to write file: %v", err)
	}
}

func TestCollectPythonFilesResolvesSelectors(t *testing.T) {
	// Precondition.
	backendDir := t.TempDir()
	writePythonFile(t, filepath.Join(backendDir, "pkg", "a.py"))
	writePythonFile(t, filepath.Join(backendDir, "pkg", "b.txt"))
	writePythonFile(t, filepath.Join(backendDir, "top.py"))
	writePythonFile(t, filepath.Join(backendDir, ".venv", "skip.py"))
	outside := filepath.Join(t.TempDir(), "secret.py")
	writePythonFile(t, outside)
	if err := os.Symlink(outside, filepath.Join(backendDir, "pkg", "link.py")); err != nil {
		t.Fatalf("Failed to create symlink: %v", err)
	}

	// Under test and postcondition.
	// A backend-relative selector resolves via the backend fallback; the
	// symlinked entry is skipped.
	files, err := collectPythonFiles([]string{"pkg"}, backendDir)
	if err != nil {
		t.Fatalf("collectPythonFiles failed: %v", err)
	}
	if len(files) != 1 || files[0] != filepath.Join(backendDir, "pkg", "a.py") {
		t.Fatalf("Expected only pkg/a.py, got %v", files)
	}

	// A whole-backend scan skips non-Python files, skip directories, and
	// symlinked entries.
	files, err = collectPythonFiles([]string{backendDir}, backendDir)
	if err != nil {
		t.Fatalf("collectPythonFiles failed: %v", err)
	}
	if len(files) != 2 {
		t.Fatalf("Expected pkg/a.py and top.py, got %v", files)
	}

	// A selector that resolves to nothing fails loudly.
	if _, err := collectPythonFiles([]string{"nonexistent"}, backendDir); err == nil {
		t.Fatalf("Expected an error for a selector that matches nothing")
	}
}
