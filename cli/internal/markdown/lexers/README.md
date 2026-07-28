# Vendored lexer definitions

XML lexer definitions copied from [chroma](https://github.com/alecthomas/chroma)
v2.23.1 (`lexers/embedded/`), MIT licensed — see LICENSE in this directory.

Only a hand-picked set of common languages is vendored here. Importing chroma's
own `lexers` package instead would embed all 268 language definitions (several
MB of binary weight); these files plus chroma's core engine cost well under 1MB.
The Go lexer is not XML-based upstream and is instead ported as Go code in
`../highlight.go`.
