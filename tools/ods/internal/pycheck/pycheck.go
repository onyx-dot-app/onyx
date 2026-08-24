// Package pycheck scans Python source for references to banned builtin names.
// It is string- and comment-aware but deliberately not a parser: string literal
// contents and comments never match, replacement fields inside f-strings are
// scanned as code, and a violation is suppressed by an 'ods: ignore[rule]'
// marker in a comment on the same physical line.
package pycheck

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// BannedName forbids bare references to a builtin name in code context.
// Attribute access ('obj.getattr') and longer identifiers ('__getattr__') never
// match.
type BannedName struct {
	// Name is the banned identifier and also the rule name accepted by ignore
	// markers, e.g. 'getattr' is suppressed by '# ods: ignore[getattr]'.
	Name string
}

// NewBannedName creates a BannedName rule for the given identifier.
func NewBannedName(name string) BannedName {
	return BannedName{Name: name}
}

// ViolationLine is a single line that references the banned name.
type ViolationLine struct {
	LineNum int
	Content string
}

// FileViolation groups the violations found in one file.
type FileViolation struct {
	RelPath        string
	ViolationLines []ViolationLine
}

// stringState tracks an open string literal across physical lines.
type stringState struct {
	open   bool
	quote  byte
	triple bool
	// fstring marks an f-prefixed literal, whose replacement fields are code.
	fstring bool
	// braceDepth is the replacement-field brace nesting depth in an f-string.
	braceDepth int
	// fieldQuote is the quote byte of a nested one-line string literal inside a
	// replacement field, or 0 when not inside one.
	fieldQuote byte
}

// scannedLine is the comment/string-aware decomposition of one physical line.
type scannedLine struct {
	// code is the source text with each string literal replaced by a single
	// space and the comment removed.
	code string
	// comment is the text after the first '#' in code context.
	comment string
	// endsInString reports whether the line ends inside an open string literal,
	// where appending a trailing comment would change the code.
	endsInString bool
}

// scanLine splits one line into code and comment given the string state left
// over from the previous line, and returns the state for the next line.
func scanLine(line string, st stringState) (scannedLine, stringState) {
	var code strings.Builder
	comment := ""
	i := 0
	for i < len(line) {
		if st.open {
			c := line[i]
			if st.fstring && st.fieldQuote != 0 {
				// A nested string literal inside a replacement field.
				if c == '\\' {
					i += 2
					continue
				}
				if c == st.fieldQuote {
					st.fieldQuote = 0
				}
				i++
				continue
			}
			if st.fstring && st.braceDepth > 0 {
				// A replacement field: its text is code.
				switch c {
				case '\'', '"':
					st.fieldQuote = c
					code.WriteByte(' ')
				case '{':
					st.braceDepth++
					code.WriteByte(' ')
				case '}':
					st.braceDepth--
					code.WriteByte(' ')
				default:
					code.WriteByte(c)
				}
				i++
				continue
			}
			if c == '\\' {
				// A backslash always consumes the next character, so an escaped
				// quote never closes the literal. This holds for raw strings
				// too: a backslash still blocks the closing quote.
				i += 2
				continue
			}
			if st.fstring && (c == '{' || c == '}') {
				if i+1 < len(line) && line[i+1] == c {
					// An escaped literal brace.
					i += 2
					continue
				}
				if c == '{' {
					st.braceDepth = 1
				}
				i++
				continue
			}
			if c == st.quote {
				if !st.triple {
					st = stringState{}
					i++
					continue
				}
				if i+2 < len(line) && line[i+1] == st.quote && line[i+2] == st.quote {
					st = stringState{}
					i += 3
					continue
				}
			}
			i++
			continue
		}
		c := line[i]
		if c == '#' {
			comment = line[i+1:]
			break
		}
		if c == '\'' || c == '"' {
			fstring := isFStringPrefix(code.String())
			// Replace the literal with one space so identifiers on either side
			// cannot merge across it; replacement fields of f-strings are fed
			// back into the code text as they are scanned.
			code.WriteByte(' ')
			if i+2 < len(line) && line[i+1] == c && line[i+2] == c {
				st = stringState{open: true, quote: c, triple: true, fstring: fstring}
				i += 3
			} else {
				st = stringState{open: true, quote: c, triple: false, fstring: fstring}
				i++
			}
			continue
		}
		code.WriteByte(c)
		i++
	}
	if st.open && !st.triple && i == len(line) {
		// A single-quoted literal survives the line break only when a trailing
		// backslash escaped it, in which case the escape jumped past the end of
		// the line above. Anything else is malformed source; close the literal
		// so it cannot poison the rest of the file.
		st = stringState{}
	}
	// A nested field string cannot span physical lines; drop the marker so a
	// malformed line cannot poison the rest of the file.
	st.fieldQuote = 0
	return scannedLine{code: code.String(), comment: comment, endsInString: st.open}, st
}

// isFStringPrefix reports whether the code text ends in a string prefix that
// contains 'f', marking the literal that follows as an f-string.
func isFStringPrefix(codeBefore string) bool {
	j := len(codeBefore)
	for j > 0 {
		c := codeBefore[j-1]
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') {
			j--
			continue
		}
		break
	}
	prefix := codeBefore[j:]
	if len(prefix) == 0 || len(prefix) > 2 {
		return false
	}
	if j > 0 && (codeBefore[j-1] == '_' || (codeBefore[j-1] >= '0' && codeBefore[j-1] <= '9')) {
		// The letters are the tail of a longer identifier, not a prefix.
		return false
	}
	hasF := false
	for k := 0; k < len(prefix); k++ {
		switch prefix[k] {
		case 'f', 'F':
			hasF = true
		case 'r', 'R', 'b', 'B', 'u', 'U':
		default:
			return false
		}
	}
	return hasF
}

// ignoreMarkerPattern matches 'ods: ignore[rule1, rule2]' inside a comment.
var ignoreMarkerPattern = regexp.MustCompile(`ods:\s*ignore\[([^\]]*)\]`)

// suppressed reports whether the comment carries an ignore marker naming rule.
func suppressed(comment string, rule string) bool {
	for _, m := range ignoreMarkerPattern.FindAllStringSubmatch(comment, -1) {
		for _, name := range strings.Split(m[1], ",") {
			if strings.TrimSpace(name) == rule {
				return true
			}
		}
	}
	return false
}

// isIdentifierRune reports whether r can appear in a Python identifier.
func isIdentifierRune(r rune) bool {
	return r == '_' || unicode.IsLetter(r) || unicode.IsDigit(r)
}

// matchesCode reports whether the scanned code text references the banned name,
// excluding attribute access like 'obj.getattr' and longer identifiers, with
// Unicode-aware identifier boundaries.
func (r BannedName) matchesCode(code string) bool {
	for start := 0; ; {
		idx := strings.Index(code[start:], r.Name)
		if idx < 0 {
			return false
		}
		begin := start + idx
		end := begin + len(r.Name)
		start = begin + 1
		if begin > 0 {
			if before, _ := utf8.DecodeLastRuneInString(code[:begin]); isIdentifierRune(before) {
				continue
			}
		}
		if end < len(code) {
			if after, _ := utf8.DecodeRuneInString(code[end:]); isIdentifierRune(after) {
				continue
			}
		}
		j := begin - 1
		for j >= 0 && (code[j] == ' ' || code[j] == '\t') {
			j--
		}
		if j >= 0 && code[j] == '.' {
			continue
		}
		return true
	}
}

// CheckContent scans Python source text and returns its violation lines.
func CheckContent(content string, rule BannedName) []ViolationLine {
	var violations []ViolationLine
	var st stringState
	for idx, line := range strings.Split(content, "\n") {
		scanned, next := scanLine(line, st)
		st = next
		if !rule.matchesCode(scanned.code) || suppressed(scanned.comment, rule.Name) {
			continue
		}
		violations = append(violations, ViolationLine{LineNum: idx + 1, Content: line})
	}
	return violations
}

// skipDirectories are directories that are never scanned.
var skipDirectories = map[string]struct{}{
	".venv":       {},
	"venv":        {},
	"__pycache__": {},
}

// isCheckablePythonFile reports whether the file should be scanned.
func isCheckablePythonFile(filePath string) bool {
	if !strings.HasSuffix(filePath, ".py") {
		return false
	}
	for _, part := range strings.Split(filePath, string(os.PathSeparator)) {
		if _, skip := skipDirectories[part]; skip {
			return false
		}
	}
	return true
}

// collectPythonFiles resolves the provided files and directories to the Python
// files inside the backend directory. A selector that resolves to nothing is an
// error rather than a silent empty scan.
func collectPythonFiles(startPoints []string, backendDir string) ([]string, error) {
	var collected []string

	for _, p := range startPoints {
		absPath, info, err := paths.ResolveInBackend(p, backendDir)
		if err != nil {
			return nil, err
		}

		if info.IsDir() {
			err := filepath.Walk(absPath, func(path string, info os.FileInfo, err error) error {
				if err != nil {
					// Fail closed: an unreadable file must not pass the check.
					return err
				}
				if info.IsDir() {
					// Do not descend into vendored or cache directories.
					if _, skip := skipDirectories[info.Name()]; skip {
						return filepath.SkipDir
					}
					return nil
				}
				// Symlinked entries are skipped so a link cannot reach a file
				// outside the backend tree.
				if info.Mode()&os.ModeSymlink == 0 && isCheckablePythonFile(path) {
					collected = append(collected, path)
				}
				return nil
			})
			if err != nil {
				return nil, err
			}
		} else if isCheckablePythonFile(absPath) {
			collected = append(collected, absPath)
		}
	}

	return collected, nil
}

// targetFiles resolves providedPaths (or the whole backend when empty) to the
// Python files to scan.
func targetFiles(providedPaths []string) ([]string, string, error) {
	backendDir, err := paths.BackendDir()
	if err != nil {
		return nil, "", err
	}
	startPoints := providedPaths
	if len(startPoints) == 0 {
		startPoints = []string{backendDir}
	}
	files, err := collectPythonFiles(startPoints, backendDir)
	if err != nil {
		return nil, "", err
	}
	return files, backendDir, nil
}

// relTo returns filePath relative to baseDir, falling back to filePath.
func relTo(baseDir string, filePath string) string {
	relPath, err := filepath.Rel(baseDir, filePath)
	if err != nil {
		return filePath
	}
	return relPath
}

// Check scans the provided paths (or the whole backend when none are given) and
// returns the per-file violations of the rule.
func Check(rule BannedName, providedPaths []string) ([]FileViolation, error) {
	files, backendDir, err := targetFiles(providedPaths)
	if err != nil {
		return nil, err
	}

	var violations []FileViolation
	for _, filePath := range files {
		data, err := os.ReadFile(filePath)
		if err != nil {
			// Fail closed: an unreadable file must not pass the check.
			return nil, err
		}
		lines := CheckContent(string(data), rule)
		if len(lines) == 0 {
			continue
		}
		violations = append(violations, FileViolation{
			RelPath:        relTo(backendDir, filePath),
			ViolationLines: lines,
		})
	}
	return violations, nil
}

// AnnotateResult reports what Annotate changed and what it could not.
type AnnotateResult struct {
	AnnotatedLines int
	AnnotatedFiles int
	// ManualFiles holds violations that cannot be annotated mechanically: the
	// line ends in a backslash continuation or inside an open string literal,
	// where a trailing comment would change the code.
	ManualFiles []FileViolation
}

// annotateFile appends the marker to every violating line of one file. It
// returns the number of lines annotated and the violations that need manual
// markers because a trailing comment would change the code there.
func annotateFile(filePath string, rule BannedName, marker string) (int, []ViolationLine, error) {
	info, err := os.Stat(filePath)
	if err != nil {
		return 0, nil, err
	}
	data, err := os.ReadFile(filePath)
	if err != nil {
		return 0, nil, err
	}

	lines := strings.Split(string(data), "\n")
	var st stringState
	var manual []ViolationLine
	annotated := 0
	for i, line := range lines {
		scanned, next := scanLine(line, st)
		st = next
		if !rule.matchesCode(scanned.code) || suppressed(scanned.comment, rule.Name) {
			continue
		}
		if scanned.endsInString || strings.HasSuffix(strings.TrimRight(scanned.code, " \t\r"), "\\") {
			manual = append(manual, ViolationLine{LineNum: i + 1, Content: line})
			continue
		}
		// Insert the marker before a CRLF line ending so the '\r' survives.
		body := strings.TrimSuffix(line, "\r")
		lines[i] = body + marker + line[len(body):]
		annotated++
	}

	if annotated > 0 {
		if err := os.WriteFile(filePath, []byte(strings.Join(lines, "\n")), info.Mode()); err != nil {
			return 0, nil, err
		}
	}
	return annotated, manual, nil
}

// Annotate appends an 'ods: ignore[rule]' marker to every violating line in the
// provided paths (or the whole backend when none are given). Suppressed lines
// are not violations, so a second run is a no-op.
func Annotate(rule BannedName, providedPaths []string) (AnnotateResult, error) {
	var result AnnotateResult
	files, backendDir, err := targetFiles(providedPaths)
	if err != nil {
		return result, err
	}

	marker := "  # ods: ignore[" + rule.Name + "]"
	for _, filePath := range files {
		annotated, manual, err := annotateFile(filePath, rule, marker)
		if err != nil {
			return result, err
		}
		if annotated > 0 {
			result.AnnotatedLines += annotated
			result.AnnotatedFiles++
		}
		if len(manual) > 0 {
			result.ManualFiles = append(result.ManualFiles, FileViolation{
				RelPath:        relTo(backendDir, filePath),
				ViolationLines: manual,
			})
		}
	}
	return result, nil
}
