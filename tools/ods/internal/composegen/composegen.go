// Package composegen renders the standalone docker compose files
// (docker-compose.yml, docker-compose.prod.yml and
// docker-compose.prod-no-letsencrypt.yml) from the shared
// docker-compose.template.yml.
//
// Template directives are line comments starting with the sentinel "#!" and
// are always stripped from the output. <variants> is a comma-separated subset
// of: default, prod, no-letsencrypt.
//
//	#!for <variants>            include the enclosed lines only for <variants>;
//	...                         must be closed with #!endfor, no nesting
//	#!endfor
//
//	#!only <variants>           shorthand: applies to exactly the next line
//
//	#!value <variants>: <text>  per-variant text for the line that follows: the
//	                            directive's own indentation plus <text> replaces
//	                            the next line for the listed variants; unlisted
//	                            variants keep the line as written. Stack several
//	                            #!value directives for three-way splits.
//
//	#!# <text>                  template-only comment, never emitted
package composegen

import (
	"fmt"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// Variant pairs a template variant name with the file it generates.
type Variant struct {
	Name     string
	Filename string
}

// Variants lists the template variants in generation order.
var Variants = []Variant{
	{Name: "default", Filename: "docker-compose.yml"},
	{Name: "prod", Filename: "docker-compose.prod.yml"},
	{Name: "no-letsencrypt", Filename: "docker-compose.prod-no-letsencrypt.yml"},
}

// TemplateName is the source template's filename.
const TemplateName = "docker-compose.template.yml"

// BannerLines is prepended to every generated file.
var BannerLines = []string{
	"# =============================================================================",
	"# THIS FILE IS GENERATED - DO NOT EDIT DIRECTLY",
	"# Source of truth: deployment/docker_compose/docker-compose.template.yml",
	"# Regenerate:      ods generate-compose --write",
	"# =============================================================================",
}

// TemplateError is a structural error in the template (bad directive,
// unclosed block, ...).
type TemplateError struct {
	Line    int
	Message string
}

func (e *TemplateError) Error() string {
	return fmt.Sprintf("%s:%d: %s", TemplateName, e.Line, e.Message)
}

func templateErrorf(line int, format string, args ...any) *TemplateError {
	return &TemplateError{Line: line, Message: fmt.Sprintf(format, args...)}
}

func isKnownVariant(name string) bool {
	for _, v := range Variants {
		if v.Name == name {
			return true
		}
	}
	return false
}

func knownVariantNames() string {
	names := make([]string, len(Variants))
	for i, v := range Variants {
		names[i] = v.Name
	}
	return strings.Join(names, ", ")
}

func parseVariantSet(spec string, lineNo int) (map[string]bool, error) {
	set := map[string]bool{}
	for _, name := range strings.Split(spec, ",") {
		if !isKnownVariant(name) {
			return nil, templateErrorf(
				lineNo, "unknown variant %q (known variants: %s)", name, knownVariantNames())
		}
		if set[name] {
			return nil, templateErrorf(lineNo, "variant %q listed twice", name)
		}
		set[name] = true
	}
	return set, nil
}

type directiveKind int

const (
	directiveComment directiveKind = iota
	directiveFor
	directiveEndfor
	directiveOnly
	directiveValue
)

type directive struct {
	kind     directiveKind
	variants map[string]bool
	text     string
}

// parseDirective parses the text after the "#!" sentinel.
func parseDirective(body string, lineNo int) (directive, error) {
	switch {
	case strings.HasPrefix(body, "#"):
		return directive{kind: directiveComment}, nil
	case strings.TrimSpace(body) == "endfor":
		return directive{kind: directiveEndfor}, nil
	case strings.HasPrefix(body, "for "):
		set, err := parseVariantSet(strings.TrimSpace(body[len("for "):]), lineNo)
		if err != nil {
			return directive{}, err
		}
		return directive{kind: directiveFor, variants: set}, nil
	case strings.HasPrefix(body, "only "):
		set, err := parseVariantSet(strings.TrimSpace(body[len("only "):]), lineNo)
		if err != nil {
			return directive{}, err
		}
		return directive{kind: directiveOnly, variants: set}, nil
	case strings.HasPrefix(body, "value "):
		rest := body[len("value "):]
		colon := strings.Index(rest, ":")
		if colon < 0 {
			return directive{}, templateErrorf(
				lineNo, "malformed #!value directive (expected '#!value <variants>: <text>')")
		}
		set, err := parseVariantSet(strings.TrimSpace(rest[:colon]), lineNo)
		if err != nil {
			return directive{}, err
		}
		return directive{
			kind:     directiveValue,
			variants: set,
			text:     strings.TrimPrefix(rest[colon+1:], " "),
		}, nil
	default:
		word, _, _ := strings.Cut(body, " ")
		return directive{}, templateErrorf(lineNo, "unknown template directive: #!%s", word)
	}
}

type pendingValue struct {
	variants map[string]bool
	text     string
}

// Render renders the template for one variant.
func Render(templateLines []string, variant string) ([]string, error) {
	if !isKnownVariant(variant) {
		return nil, fmt.Errorf("unknown variant: %s", variant)
	}

	var out []string
	var openForVariants map[string]bool
	openForLine := 0
	var onlyVariants map[string]bool
	onlyLine := 0
	// Stacked #!value directives waiting for their base line, plus the union of
	// variants they claim (to reject double claims / fully-claimed base lines).
	var values []pendingValue
	claimed := map[string]bool{}

	inScope := func() bool { return openForVariants == nil || openForVariants[variant] }

	for i, raw := range templateLines {
		lineNo := i + 1
		stripped := strings.TrimLeft(raw, " \t")
		if strings.HasPrefix(stripped, "#!") {
			indent := raw[:len(raw)-len(stripped)]
			d, err := parseDirective(stripped[2:], lineNo)
			if err != nil {
				return nil, err
			}
			if onlyVariants != nil {
				return nil, templateErrorf(
					lineNo, "#!only must be immediately followed by a content line")
			}
			if len(values) > 0 && d.kind != directiveValue {
				return nil, templateErrorf(
					lineNo, "#!value must be immediately followed by a content line or another #!value")
			}
			switch d.kind {
			case directiveComment:
			case directiveFor:
				if openForVariants != nil {
					return nil, templateErrorf(
						lineNo, "nested #!for (previous block opened at line %d)", openForLine)
				}
				openForVariants = d.variants
				openForLine = lineNo
			case directiveEndfor:
				if openForVariants == nil {
					return nil, templateErrorf(lineNo, "#!endfor without matching #!for")
				}
				openForVariants = nil
			case directiveOnly:
				onlyVariants = d.variants
				onlyLine = lineNo
			case directiveValue:
				var overlap []string
				for name := range d.variants {
					if claimed[name] {
						overlap = append(overlap, name)
					}
				}
				if len(overlap) > 0 {
					sort.Strings(overlap)
					return nil, templateErrorf(
						lineNo, "variant(s) %s already claimed by a stacked #!value",
						strings.Join(overlap, ", "))
				}
				for name := range d.variants {
					claimed[name] = true
				}
				if len(claimed) >= len(Variants) {
					return nil, templateErrorf(
						lineNo, "stacked #!value directives cover every variant; "+
							"the base line below would never be emitted")
				}
				text := ""
				if d.text != "" {
					text = indent + d.text
				}
				values = append(values, pendingValue{variants: d.variants, text: text})
			}
			continue
		}

		// Content line.
		switch {
		case onlyVariants != nil:
			include := onlyVariants[variant] && inScope()
			onlyVariants = nil
			if include {
				out = append(out, raw)
			}
		case len(values) > 0:
			line := raw
			for _, v := range values {
				if v.variants[variant] {
					line = v.text
					break
				}
			}
			values = nil
			claimed = map[string]bool{}
			if inScope() {
				out = append(out, line)
			}
		case inScope():
			out = append(out, raw)
		}
	}

	if openForVariants != nil {
		return nil, templateErrorf(openForLine, "unclosed #!for block (missing #!endfor)")
	}
	if onlyVariants != nil {
		return nil, templateErrorf(onlyLine, "#!only at end of file")
	}
	if len(values) > 0 {
		return nil, templateErrorf(len(templateLines), "#!value at end of file")
	}
	return out, nil
}

// GenerateAll renders every variant and returns filename -> full file content
// (banner + rendered body + trailing newline). Every output is checked for
// leaked directives and validated as parseable YAML.
func GenerateAll(templateLines []string) (map[string]string, error) {
	results := make(map[string]string, len(Variants))
	for _, v := range Variants {
		body, err := Render(templateLines, v.Name)
		if err != nil {
			return nil, err
		}
		for _, line := range body {
			if strings.HasPrefix(strings.TrimLeft(line, " \t"), "#!") {
				return nil, fmt.Errorf(
					"internal error: directive leaked into %s: %q", v.Filename, line)
			}
		}
		lines := make([]string, 0, len(BannerLines)+len(body))
		lines = append(lines, BannerLines...)
		lines = append(lines, body...)
		content := strings.Join(lines, "\n") + "\n"

		var doc any
		if err := yaml.Unmarshal([]byte(content), &doc); err != nil {
			return nil, fmt.Errorf("%s: generated YAML does not parse: %w", v.Filename, err)
		}
		results[v.Filename] = content
	}
	return results, nil
}
