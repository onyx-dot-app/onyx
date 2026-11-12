// Package sanitize neutralises untrusted text before it reaches a terminal.
package sanitize

import (
	"strings"
	"unicode/utf8"

	"github.com/charmbracelet/x/ansi"
)

// Terminal removes escape sequences, C0 controls except \n and \t, DEL, C1
// controls and invalid UTF-8 from s. ansi.Strip alone keeps lone controls
// such as BEL, and a sequence split across stream chunks survives it, so the
// per-rune filter is what makes the output safe.
func Terminal(s string) string {
	s = ansi.Strip(s)
	var b strings.Builder
	b.Grow(len(s))
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		i += size
		switch {
		case r == utf8.RuneError && size == 1:
		case r == '\n' || r == '\t':
			b.WriteRune(r)
		case r < 0x20, r == 0x7f, r >= 0x80 && r <= 0x9f:
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// Line is Terminal for single-line fields: it also turns \n and \t into
// spaces so a value cannot add rows or columns to a table or bar.
func Line(s string) string {
	return strings.Map(func(r rune) rune {
		if r == '\n' || r == '\t' {
			return ' '
		}
		return r
	}, Terminal(s))
}
