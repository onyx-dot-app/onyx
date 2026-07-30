package install

import (
	"slices"
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

// COMPOSE_PROFILES is a list, and only one of its entries belongs to the
// deployment mode (s3-filestore, which runs MinIO). The rest are the user's,
// so mode changes add and drop that one entry instead of rewriting the value.

// hasProfile reports whether a COMPOSE_PROFILES value activates profile.
func hasProfile(list, profile string) bool {
	return slices.Contains(profileList(list), profile)
}

// withoutProfile drops profile, keeping every other entry in its order.
func withoutProfile(list, profile string) string {
	kept := slices.DeleteFunc(profileList(list), func(p string) bool { return p == profile })
	return strings.Join(kept, ",")
}

// withProfile appends profile, leaving a list that already has it untouched.
func withProfile(list, profile string) string {
	if hasProfile(list, profile) {
		return list
	}
	return strings.Join(append(profileList(list), profile), ",")
}

// profileList splits a COMPOSE_PROFILES value, dropping blanks left by an
// empty value or a stray comma.
func profileList(list string) []string {
	var out []string
	for _, p := range strings.Split(list, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
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
