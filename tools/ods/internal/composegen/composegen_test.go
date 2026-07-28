package composegen

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var allVariants = []string{"default", "prod", "no-letsencrypt"}

func mustRender(t *testing.T, lines []string, variant string) []string {
	t.Helper()
	out, err := Render(lines, variant)
	if err != nil {
		t.Fatalf("Render(%q) failed: %v", variant, err)
	}
	return out
}

func assertRender(t *testing.T, lines []string, variant string, want []string) {
	t.Helper()
	got := mustRender(t, lines, variant)
	if len(got) != len(want) {
		t.Fatalf("Render(%q) = %q, want %q", variant, got, want)
	}
	for i := range got {
		if got[i] != want[i] {
			t.Fatalf("Render(%q) = %q, want %q", variant, got, want)
		}
	}
}

func TestPlainLinesFlowToEveryVariant(t *testing.T) {
	lines := []string{"name: onyx", "", "services:"}
	for _, variant := range allVariants {
		assertRender(t, lines, variant, lines)
	}
}

func TestForBlockIncludesOnlyListedVariants(t *testing.T) {
	lines := []string{
		"a",
		"#!for prod,no-letsencrypt",
		"b",
		"c",
		"#!endfor",
		"d",
	}
	assertRender(t, lines, "default", []string{"a", "d"})
	assertRender(t, lines, "prod", []string{"a", "b", "c", "d"})
	assertRender(t, lines, "no-letsencrypt", []string{"a", "b", "c", "d"})
}

func TestAdjacentForBlocksAreMutuallyExclusive(t *testing.T) {
	lines := []string{
		"#!for default",
		"# commented-out service",
		"#!endfor",
		"#!for prod",
		"active-service:",
		"#!endfor",
	}
	assertRender(t, lines, "default", []string{"# commented-out service"})
	assertRender(t, lines, "prod", []string{"active-service:"})
	assertRender(t, lines, "no-letsencrypt", nil)
}

func TestOnlyAppliesToExactlyOneLine(t *testing.T) {
	lines := []string{
		"a",
		"    #!only default",
		`    profiles: ["s3-filestore"]`,
		"b",
	}
	assertRender(t, lines, "default", []string{"a", `    profiles: ["s3-filestore"]`, "b"})
	assertRender(t, lines, "prod", []string{"a", "b"})
}

func TestValueReplacesLineWithDirectiveIndentation(t *testing.T) {
	lines := []string{
		"      #!value prod,no-letsencrypt: - AUTH_TYPE=${AUTH_TYPE:-oidc}",
		"      - AUTH_TYPE=${AUTH_TYPE:-basic}",
	}
	assertRender(t, lines, "default", []string{"      - AUTH_TYPE=${AUTH_TYPE:-basic}"})
	assertRender(t, lines, "prod", []string{"      - AUTH_TYPE=${AUTH_TYPE:-oidc}"})
	assertRender(t, lines, "no-letsencrypt", []string{"      - AUTH_TYPE=${AUTH_TYPE:-oidc}"})
}

func TestValueThreeWayStack(t *testing.T) {
	lines := []string{
		"  #!value prod: run prod",
		"  #!value no-letsencrypt: run no-le",
		"  run default",
	}
	assertRender(t, lines, "default", []string{"  run default"})
	assertRender(t, lines, "prod", []string{"  run prod"})
	assertRender(t, lines, "no-letsencrypt", []string{"  run no-le"})
}

func TestValueTextMayContainColons(t *testing.T) {
	lines := []string{
		"  #!value prod: image: onyxdotapp/x:${TAG:-latest}",
		"  image: fallback",
	}
	assertRender(t, lines, "prod", []string{"  image: onyxdotapp/x:${TAG:-latest}"})
}

func TestDirectivesInsideExcludedForBlockAreConsumed(t *testing.T) {
	lines := []string{
		"#!for prod",
		"  #!only prod",
		"  a",
		"  #!value prod: b2",
		"  b",
		"#!endfor",
		"c",
	}
	assertRender(t, lines, "default", []string{"c"})
	assertRender(t, lines, "prod", []string{"  a", "  b2", "c"})
}

func TestTemplateCommentIsStripped(t *testing.T) {
	lines := []string{"#!# only for template readers", "a"}
	for _, variant := range allVariants {
		assertRender(t, lines, variant, []string{"a"})
	}
}

func TestNoDirectiveEverLeaks(t *testing.T) {
	lines := []string{
		"#!# comment",
		"#!for default",
		"a",
		"#!endfor",
		"  #!only prod",
		"  b",
		"  #!value prod: c2",
		"  c",
	}
	for _, variant := range allVariants {
		for _, line := range mustRender(t, lines, variant) {
			if strings.HasPrefix(strings.TrimLeft(line, " \t"), "#!") {
				t.Fatalf("directive leaked into %q output: %q", variant, line)
			}
		}
	}
}

func assertTemplateError(t *testing.T, lines []string, fragment string) {
	t.Helper()
	_, err := Render(lines, "default")
	if err == nil {
		t.Fatalf("expected error containing %q, got nil", fragment)
	}
	var templateErr *TemplateError
	if !errors.As(err, &templateErr) {
		t.Fatalf("expected *TemplateError, got %T: %v", err, err)
	}
	if !strings.Contains(err.Error(), fragment) {
		t.Fatalf("error %q does not contain %q", err.Error(), fragment)
	}
}

func TestUnclosedFor(t *testing.T) {
	assertTemplateError(t, []string{"#!for prod", "a"}, "unclosed #!for")
}

func TestNestedFor(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!for prod", "#!for default", "a", "#!endfor", "#!endfor"}, "nested #!for")
}

func TestEndforWithoutFor(t *testing.T) {
	assertTemplateError(t, []string{"a", "#!endfor"}, "#!endfor without matching #!for")
}

func TestOnlyFollowedByDirective(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!only prod", "#!for default", "a", "#!endfor"},
		"#!only must be immediately followed by a content line")
}

func TestOnlyAtEndOfFile(t *testing.T) {
	assertTemplateError(t, []string{"a", "#!only prod"}, "#!only at end of file")
}

func TestValueAtEndOfFile(t *testing.T) {
	assertTemplateError(t, []string{"a", "#!value prod: x"}, "#!value at end of file")
}

func TestValueFollowedByNonValueDirective(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!value prod: x", "#!for default", "a", "#!endfor"},
		"#!value must be immediately followed by a content line")
}

func TestValueDuplicateClaim(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!value prod: x", "#!value prod,no-letsencrypt: y", "base"},
		"already claimed")
}

func TestValueCoveringAllVariants(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!value prod,no-letsencrypt,default: x", "base"},
		"cover every variant")
}

func TestUnknownVariant(t *testing.T) {
	assertTemplateError(t, []string{"#!for production", "a", "#!endfor"}, "unknown variant")
}

func TestVariantListedTwice(t *testing.T) {
	assertTemplateError(t, []string{"#!only prod,prod", "a"}, "listed twice")
}

func TestUnknownDirective(t *testing.T) {
	assertTemplateError(t, []string{"#!fro prod", "a"}, "unknown template directive")
}

func TestMalformedValue(t *testing.T) {
	assertTemplateError(t, []string{"#!value prod x", "a"}, "malformed #!value")
}

func TestGenerateAllAddsBannerAndValidatesYaml(t *testing.T) {
	lines := []string{"name: onyx", "services:", "  api_server:", "    image: x"}
	results, err := GenerateAll(lines)
	if err != nil {
		t.Fatalf("GenerateAll failed: %v", err)
	}
	if len(results) != len(Variants) {
		t.Fatalf("expected %d outputs, got %d", len(Variants), len(results))
	}
	for _, v := range Variants {
		content, ok := results[v.Filename]
		if !ok {
			t.Fatalf("missing output for %s", v.Filename)
		}
		if !strings.HasPrefix(content, BannerLines[0]+"\n"+BannerLines[1]) {
			t.Fatalf("%s does not start with the generated-file banner", v.Filename)
		}
		if !strings.HasSuffix(content, "\n") {
			t.Fatalf("%s does not end with a newline", v.Filename)
		}
	}
}

func TestGenerateAllRejectsInvalidYaml(t *testing.T) {
	lines := []string{"services:", "\t- tabs are not valid yaml indentation"}
	if _, err := GenerateAll(lines); err == nil {
		t.Fatal("expected YAML validation error, got nil")
	}
}

// TestCheckedInFilesMatchTemplate renders the real template from the repo and
// asserts the checked-in generated files are up to date, making `go test` a
// drift gate independent of the docker-compose-sync pre-commit hook.
func TestCheckedInFilesMatchTemplate(t *testing.T) {
	dir := filepath.Join("..", "..", "..", "..", "deployment", "docker_compose")

	data, err := os.ReadFile(filepath.Join(dir, TemplateName))
	if err != nil {
		t.Fatalf("failed to read %s: %v", TemplateName, err)
	}
	templateLines := strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")

	results, err := GenerateAll(templateLines)
	if err != nil {
		t.Fatalf("GenerateAll failed on the real template: %v", err)
	}

	for _, v := range Variants {
		checkedIn, err := os.ReadFile(filepath.Join(dir, v.Filename))
		if err != nil {
			t.Fatalf("failed to read %s: %v", v.Filename, err)
		}
		if string(checkedIn) != results[v.Filename] {
			t.Errorf("%s does not match %s: run `ods generate-compose --write` and commit the result",
				v.Filename, TemplateName)
		}
	}
}
