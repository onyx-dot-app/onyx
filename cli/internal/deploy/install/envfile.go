package install

import (
	"strings"
)

// .env manipulation, matching install.sh's sed/grep semantics: SetVar
// replaces every uncommented `KEY=...` line (appending when none exists),
// SetVarUncomment additionally matches commented `# KEY=...` lines and
// uncomments them, Var reads the first uncommented value with quotes and
// spaces stripped.

// SetVar sets KEY=value, replacing all `^KEY=` lines or appending.
func SetVar(content, key, value string) string {
	return setVar(content, key, value, false)
}

// SetVarUncomment sets KEY=value, also replacing commented `^#* *KEY=` lines.
func SetVarUncomment(content, key, value string) string {
	return setVar(content, key, value, true)
}

func setVar(content, key, value string, matchCommented bool) string {
	lines := strings.Split(content, "\n")
	replaced := false
	for i, line := range lines {
		if matchesKey(line, key, matchCommented) {
			lines[i] = key + "=" + value
			replaced = true
		}
	}
	if replaced {
		return strings.Join(lines, "\n")
	}
	if !strings.HasSuffix(content, "\n") && content != "" {
		content += "\n"
	}
	return content + key + "=" + value + "\n"
}

// Var returns the value of the first `KEY=` line ("" if absent), with spaces
// and quotes stripped (install.sh: cut -d= -f2 | tr -d ' "\” ).
func Var(content, key string) string {
	for _, line := range strings.Split(content, "\n") {
		if rest, ok := strings.CutPrefix(line, key+"="); ok {
			return strings.NewReplacer(" ", "", `"`, "", "'", "").Replace(rest)
		}
	}
	return ""
}

func matchesKey(line, key string, matchCommented bool) bool {
	if strings.HasPrefix(line, key+"=") {
		return true
	}
	if !matchCommented {
		return false
	}
	// `^#* *KEY=`: any number of #, then spaces, then the assignment.
	rest := strings.TrimLeft(line, "#")
	rest = strings.TrimLeft(rest, " ")
	return rest != line && strings.HasPrefix(rest, key+"=")
}
