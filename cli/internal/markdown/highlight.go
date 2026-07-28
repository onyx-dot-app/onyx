package markdown

import (
	"embed"
	"strings"
	"sync"

	"charm.land/lipgloss/v2"
	chroma "github.com/alecthomas/chroma/v2"
)

// Syntax highlighting uses chroma's core engine with a hand-picked set of
// language definitions embedded below. Chroma's own lexers package is
// deliberately not imported: it embeds all 268 language definitions and
// costs several MB of binary weight; this set costs well under 1MB.
//
// The XML files under lexers/ are vendored verbatim from
// github.com/alecthomas/chroma/v2 v2.23.1 (lexers/embedded/), MIT licensed —
// see lexers/LICENSE and lexers/README.md for provenance.

//go:embed lexers/*.xml
var lexerFS embed.FS

// lexerFiles lists the vendored language definitions. Fence tags resolve
// through each definition's own name, aliases, and filename globs, so e.g.
// "py", "python3", "sh", and "ts" all work without an explicit alias table.
var lexerFiles = []string{
	"lexers/bash.xml",
	"lexers/c.xml",
	"lexers/c++.xml",
	"lexers/css.xml",
	"lexers/diff.xml",
	"lexers/docker.xml",
	"lexers/html.xml",
	"lexers/java.xml",
	"lexers/javascript.xml",
	"lexers/json.xml",
	"lexers/kotlin.xml",
	"lexers/makefile.xml",
	"lexers/php.xml",
	"lexers/python.xml",
	"lexers/ruby.xml",
	"lexers/rust.xml",
	"lexers/sql.xml",
	"lexers/swift.xml",
	"lexers/toml.xml",
	"lexers/typescript.xml",
	"lexers/yaml.xml",
}

// registry is built once on first use. A shared registry (rather than
// standalone lexers) is required because some definitions delegate to other
// languages by name — e.g. Dockerfile RUN lines are lexed as Bash — and those
// references resolve through the lexer's registry.
var registry = sync.OnceValue(func() *chroma.LexerRegistry {
	r := chroma.NewLexerRegistry()
	for _, path := range lexerFiles {
		if lexer, err := chroma.NewXMLLexer(lexerFS, path); err == nil {
			r.Register(chroma.Coalesce(lexer))
		}
	}
	r.Register(goLexer())
	return r
})

func lexerFor(lang string) chroma.Lexer {
	lang = strings.TrimSpace(lang)
	if lang == "" {
		return nil
	}
	return registry().Get(lang)
}

// highlightLines tokenizes code and returns one styled string per line.
// Styling is applied per line so no SGR state crosses the code-block gutter
// prefix. Returns false when the language is unsupported or tokenization
// fails, in which case the caller falls back to unhighlighted rendering.
func highlightLines(code, lang string) (lines []string, ok bool) {
	// A delegation to a language missing from the registry panics inside
	// chroma; degrade to unhighlighted output instead.
	defer func() {
		if recover() != nil {
			lines, ok = nil, false
		}
	}()
	lexer := lexerFor(lang)
	if lexer == nil {
		return nil, false
	}
	it, err := lexer.Tokenise(nil, code)
	if err != nil {
		return nil, false
	}
	var cur strings.Builder
	for tok := it(); tok != chroma.EOF; tok = it() {
		style := tokenStyle(tok.Type)
		parts := strings.Split(tok.Value, "\n")
		for i, part := range parts {
			if i > 0 {
				lines = append(lines, cur.String())
				cur.Reset()
			}
			if part != "" {
				cur.WriteString(style.Render(part))
			}
		}
	}
	if cur.Len() > 0 {
		lines = append(lines, cur.String())
	}
	return lines, true
}

var (
	hlKeyword  = lipgloss.NewStyle().Foreground(accentColor).Bold(true)
	hlString   = lipgloss.NewStyle().Foreground(lipgloss.Color("#98c379"))
	hlNumber   = lipgloss.NewStyle().Foreground(lipgloss.Color("#d19a66"))
	hlComment  = lipgloss.NewStyle().Foreground(dimColor).Italic(true)
	hlFunction = lipgloss.NewStyle().Foreground(lipgloss.Color("#61afef"))
	hlPlain    = lipgloss.NewStyle().Foreground(codeColor)
)

func tokenStyle(t chroma.TokenType) lipgloss.Style {
	switch {
	case t.Category() == chroma.Keyword:
		return hlKeyword
	case t.Category() == chroma.Comment:
		return hlComment
	case t.SubCategory() == chroma.LiteralString:
		return hlString
	case t.SubCategory() == chroma.LiteralNumber:
		return hlNumber
	case t == chroma.NameFunction || t == chroma.NameBuiltin:
		return hlFunction
	default:
		return hlPlain
	}
}

// goLexer is ported from chroma's Go lexer (MIT — see lexers/LICENSE), which
// upstream lives as Go code in the all-languages lexers package rather than
// as an XML definition. Raw strings are simplified to plain string literals
// (upstream delegates them to the Go-template lexer).
func goLexer() chroma.Lexer {
	lexer := chroma.MustNewLexer(
		&chroma.Config{
			Name:    "Go",
			Aliases: []string{"go", "golang"},
		},
		func() chroma.Rules {
			return chroma.Rules{
				"root": {
					{Pattern: `\n`, Type: chroma.TextWhitespace},
					{Pattern: `\s+`, Type: chroma.TextWhitespace},
					{Pattern: `//[^\n\r]*`, Type: chroma.CommentSingle},
					{Pattern: `/(\\\n)?[*](.|\n)*?[*](\\\n)?/`, Type: chroma.CommentMultiline},
					{Pattern: `(import|package)\b`, Type: chroma.KeywordNamespace},
					{Pattern: `(var|func|struct|map|chan|type|interface|const)\b`, Type: chroma.KeywordDeclaration},
					{Pattern: chroma.Words(``, `\b`, `break`, `default`, `select`, `case`, `defer`, `go`, `else`, `goto`, `switch`, `fallthrough`, `if`, `range`, `continue`, `for`, `return`), Type: chroma.Keyword},
					{Pattern: `(true|false|iota|nil)\b`, Type: chroma.KeywordConstant},
					{Pattern: chroma.Words(``, `\b`, `uint`, `uint8`, `uint16`, `uint32`, `uint64`, `int`, `int8`, `int16`, `int32`, `int64`, `float`, `float32`, `float64`, `complex64`, `complex128`, `byte`, `rune`, `string`, `bool`, `error`, `uintptr`, `any`), Type: chroma.KeywordType},
					{Pattern: `\d+(\.\d+[eE][+\-]?\d+|\.\d*|[eE][+\-]?\d+)i?`, Type: chroma.LiteralNumberFloat},
					{Pattern: `0[xX][0-9a-fA-F_]+`, Type: chroma.LiteralNumberHex},
					{Pattern: `0b[01_]+`, Type: chroma.LiteralNumberBin},
					{Pattern: `(0|[1-9][0-9_]*)i?`, Type: chroma.LiteralNumberInteger},
					{Pattern: `'(\\['"\\abfnrtv]|\\x[0-9a-fA-F]{2}|\\[0-7]{1,3}|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|[^\\])'`, Type: chroma.LiteralStringChar},
					{Pattern: "(`)([^`]*)(`)", Type: chroma.LiteralString},
					{Pattern: `"(\\\\|\\"|[^"])*"`, Type: chroma.LiteralString},
					{Pattern: `(<<=|>>=|<<|>>|<=|>=|&\^=|&\^|\+=|-=|\*=|/=|%=|&=|\|=|&&|\|\||<-|\+\+|--|==|!=|:=|\.\.\.|[+\-*/%&])`, Type: chroma.Operator},
					{Pattern: `([a-zA-Z_]\w*)(\()`, Type: chroma.ByGroups(chroma.NameFunction, chroma.Punctuation)},
					{Pattern: `[|^<>=!()\[\]{}.,;:~]`, Type: chroma.Punctuation},
					{Pattern: `[^\W\d]\w*`, Type: chroma.NameOther},
				},
			}
		},
	)
	return chroma.Coalesce(lexer)
}
