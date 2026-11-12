package audit

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSupplementalInventoryUsesSharedImageReport(t *testing.T) {
	directory := t.TempDir()
	docker := `#!/bin/sh
case "$1" in
 create) echo fixture-container;;
 cp) test "$MISSING_SBOM" != true || exit 1; cp "$SBOM_FIXTURE" "$3";;
 run) test "$SCANNER_FAILURE" != true || exit 1; cat "$GRYPE_FIXTURE";;
 rm) ;;
 *) exit 99;;
esac
`
	write := func(name, content string) string {
		path := filepath.Join(directory, name)
		if err := os.WriteFile(path, []byte(content), 0700); err != nil {
			t.Fatal(err)
		}
		return path
	}
	write("docker", docker)
	t.Setenv("PATH", directory+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("SBOM_FIXTURE", write("sbom.json", `{"components":[{"name":"example","version":"1.0.0","cpe":"cpe:2.3:a:vendor:example:1.0.0:*:*:*:*:*:*:*"}]}`))
	t.Setenv("GRYPE_FIXTURE", write("grype.json", `{"matches":[{"vulnerability":{"id":"CVE-TEST","severity":"Critical","description":"test finding","fix":{"versions":["1.0.1"]}},"artifact":{"name":"example","version":"1.0.0","type":"binary"}}]}`))
	original := scanOSImage
	scanOSImage = func(string, bool) ([]Finding, error) { return nil, nil }
	t.Cleanup(func() { scanOSImage = original })
	opts := ImageOptions{Image: "fixture", SBOMs: []string{"/inventory.cdx.json"}, Format: "json", FailOn: SeverityCritical, Stderr: io.Discard}
	var out bytes.Buffer
	opts.Stdout = &out
	result, err := RunImage(opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Blocking) != 1 || !strings.Contains(out.String(), "grype-sbom") {
		t.Fatalf("missing shared findings: %s", out.String())
	}
	opts.IgnoreURL = write("ignores.json", `{"ignores":[{"id":"CVE-TEST","reason":"reviewed"}]}`)
	out.Reset()
	result, err = RunImage(opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Blocking) != 0 || len(result.Ignored) != 1 {
		t.Fatalf("shared exception was not applied: %+v", result)
	}
	for _, invalid := range []string{`{"components":[]}`, `{"components":[{"name":"example","version":"1.0.0","cpe":"cpe:2.3:a:vendor:example:2.0.0:*:*:*:*:*:*:*"}]}`} {
		path := write("invalid-sbom.json", invalid)
		t.Setenv("SBOM_FIXTURE", path)
		if _, err := RunImage(opts); err == nil {
			t.Fatal("invalid required inventory passed")
		}
	}
	t.Setenv("SBOM_FIXTURE", filepath.Join(directory, "sbom.json"))
	for _, failure := range []string{"MISSING_SBOM", "SCANNER_FAILURE"} {
		t.Setenv(failure, "true")
		if _, err := RunImage(opts); err == nil {
			t.Fatalf("%s passed", failure)
		}
		t.Setenv(failure, "")
	}
}
