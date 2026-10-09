# Vendored lexer definitions

XML lexer definitions copied **verbatim** from
[chroma](https://github.com/alecthomas/chroma) v2.23.1 (`lexers/embedded/`),
MIT licensed — see [LICENSE](./LICENSE) in this directory (chroma's `COPYING`,
copyright Alec Thomas). Chroma's grammars are in turn largely ports of
[Pygments](https://pygments.org/) lexer definitions (BSD-2-Clause).

Only a hand-picked set of common languages is vendored here. Importing chroma's
own `lexers` package instead would embed all 268 language definitions (several
MB of binary weight); these files plus chroma's core engine cost well under 1MB.
The Go lexer is not XML-based upstream and is instead ported as Go code in
`../highlight.go`.

Because the files are unmodified and chroma is still a regular `go.mod`
dependency, each file can be diffed against the same path in the module cache
(`github.com/alecthomas/chroma/v2@v2.23.1/lexers/embedded/`) to verify
provenance or to refresh a grammar.
