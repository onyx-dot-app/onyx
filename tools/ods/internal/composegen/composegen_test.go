package composegen

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var allVariants = []string{"default", "no-letsencrypt"}

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
		"#!for no-letsencrypt",
		"b",
		"c",
		"#!endfor",
		"d",
	}
	assertRender(t, lines, "default", []string{"a", "d"})
	assertRender(t, lines, "no-letsencrypt", []string{"a", "b", "c", "d"})
}

func TestAdjacentForBlocksAreMutuallyExclusive(t *testing.T) {
	lines := []string{
		"#!for default",
		"# commented-out service",
		"#!endfor",
		"#!for no-letsencrypt",
		"active-service:",
		"#!endfor",
	}
	assertRender(t, lines, "default", []string{"# commented-out service"})
	assertRender(t, lines, "no-letsencrypt", []string{"active-service:"})
}

func TestOnlyAppliesToExactlyOneLine(t *testing.T) {
	lines := []string{
		"a",
		"    #!only default",
		`    profiles: ["s3-filestore"]`,
		"b",
	}
	assertRender(t, lines, "default", []string{"a", `    profiles: ["s3-filestore"]`, "b"})
	assertRender(t, lines, "no-letsencrypt", []string{"a", "b"})
}

func TestValueReplacesLineWithDirectiveIndentation(t *testing.T) {
	lines := []string{
		"      #!value no-letsencrypt: - AUTH_TYPE=${AUTH_TYPE:-oidc}",
		"      - AUTH_TYPE=${AUTH_TYPE:-basic}",
	}
	assertRender(t, lines, "default", []string{"      - AUTH_TYPE=${AUTH_TYPE:-basic}"})
	assertRender(t, lines, "no-letsencrypt", []string{"      - AUTH_TYPE=${AUTH_TYPE:-oidc}"})
}

func TestValueTextMayContainColons(t *testing.T) {
	lines := []string{
		"  #!value no-letsencrypt: image: onyxdotapp/x:${TAG:-latest}",
		"  image: fallback",
	}
	assertRender(t, lines, "no-letsencrypt", []string{"  image: onyxdotapp/x:${TAG:-latest}"})
}

func TestDirectivesInsideExcludedForBlockAreConsumed(t *testing.T) {
	lines := []string{
		"#!for no-letsencrypt",
		"  #!only no-letsencrypt",
		"  a",
		"  #!value no-letsencrypt: b2",
		"  b",
		"#!endfor",
		"c",
	}
	assertRender(t, lines, "default", []string{"c"})
	assertRender(t, lines, "no-letsencrypt", []string{"  a", "  b2", "c"})
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
		"  #!only no-letsencrypt",
		"  b",
		"  #!value no-letsencrypt: c2",
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
	assertTemplateError(t, []string{"#!for no-letsencrypt", "a"}, "unclosed #!for")
}

func TestNestedFor(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!for no-letsencrypt", "#!for default", "a", "#!endfor", "#!endfor"}, "nested #!for")
}

func TestEndforWithoutFor(t *testing.T) {
	assertTemplateError(t, []string{"a", "#!endfor"}, "#!endfor without matching #!for")
}

func TestOnlyFollowedByDirective(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!only no-letsencrypt", "#!for default", "a", "#!endfor"},
		"#!only must be immediately followed by a content line")
}

func TestOnlyAtEndOfFile(t *testing.T) {
	assertTemplateError(t, []string{"a", "#!only no-letsencrypt"}, "#!only at end of file")
}

func TestValueAtEndOfFile(t *testing.T) {
	assertTemplateError(t, []string{"a", "#!value no-letsencrypt: x"}, "#!value at end of file")
}

func TestValueFollowedByNonValueDirective(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!value no-letsencrypt: x", "#!for default", "a", "#!endfor"},
		"#!value must be immediately followed by a content line")
}

func TestValueDuplicateClaim(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!value no-letsencrypt: x", "#!value no-letsencrypt,default: y", "base"},
		"already claimed")
}

func TestValueCoveringAllVariants(t *testing.T) {
	assertTemplateError(t,
		[]string{"#!value no-letsencrypt,default: x", "base"},
		"cover every variant")
}

func TestUnknownVariant(t *testing.T) {
	assertTemplateError(t, []string{"#!for production", "a", "#!endfor"}, "unknown variant")
	// prod was retired when docker-compose.prod.yml became a hand-maintained
	// overlay; a directive still naming it must fail loudly.
	assertTemplateError(t, []string{"#!for prod", "a", "#!endfor"}, "unknown variant")
}

func TestVariantListedTwice(t *testing.T) {
	assertTemplateError(t, []string{"#!only no-letsencrypt,no-letsencrypt", "a"}, "listed twice")
}

func TestUnknownDirective(t *testing.T) {
	assertTemplateError(t, []string{"#!fro no-letsencrypt", "a"}, "unknown template directive")
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

// TestProdOverlayIsNotGenerated guards the retirement of the prod variant:
// docker-compose.prod.yml is a hand-maintained overlay now, and a generator
// (e.g. a stale released ods) writing the generated-file banner into it means
// it was clobbered with a rendered standalone file.
func TestProdOverlayIsNotGenerated(t *testing.T) {
	dir := filepath.Join("..", "..", "..", "..", "deployment", "docker_compose")
	data, err := os.ReadFile(filepath.Join(dir, "docker-compose.prod.yml"))
	if err != nil {
		t.Fatalf("failed to read docker-compose.prod.yml: %v", err)
	}
	if strings.Contains(string(data), BannerLines[1]) {
		t.Error("docker-compose.prod.yml carries the generated-file banner — it is a hand-maintained overlay and must not be regenerated from the template")
	}
	for _, v := range Variants {
		if v.Filename == "docker-compose.prod.yml" {
			t.Error("docker-compose.prod.yml must not be a composegen variant")
		}
	}
}
