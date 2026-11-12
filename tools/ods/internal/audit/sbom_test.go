package audit

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestSupplementalInventoryUsesSharedImageReport(t *testing.T) {
	directory := t.TempDir()
	docker := `#!/bin/sh
case "$1" in
 create) test "$CREATE_FAILURE" != true || exit 1; echo fixture-container;;
 cp) test "$COPY_NO_FILE" != true || exit 0; test "$MISSING_SBOM" != true || exit 1; cp "$SBOM_FIXTURE" "$3";;
 run)
 test "$SCANNER_FAILURE" != true || exit 1
 shift
 test "$1 $2 $3 $4" = '--rm --env GRYPE_CHECK_FOR_APP_UPDATE=false --mount' || exit 91
 case "$5" in type=bind,source=*,target=/inventory,readonly) ;; *) exit 92;; esac
 mounted=${5#type=bind,source=}; mounted=${mounted%,target=/inventory,readonly}
 test -f "$mounted/inventory.json" || exit 93
 shift 5
 if test -n "$SSL_CERT_FILE"; then
  test "$1 $2 $3 $4" = "--mount type=bind,source=$SSL_CERT_FILE,target=/certs/ca.pem,readonly --env SSL_CERT_FILE=/certs/ca.pem" || exit 94
  shift 4
 fi
 test "$1" = "$EXPECTED_SCANNER" || exit 95
 shift
 test "$*" = 'sbom:/inventory/inventory.json --output json' || exit 96
 cat "$GRYPE_FIXTURE";;
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
	t.Setenv("BASE_IMAGE_REGISTRY", "")
	t.Setenv("SSL_CERT_FILE", "")
	t.Setenv("EXPECTED_SCANNER", "docker.io/"+grypeImage)
	t.Setenv("PATH", directory+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("SBOM_FIXTURE", write("sbom.json", `{"components":[{"type":"application","name":"example","version":"1.0.0","cpe":"cpe:2.3:a:vendor:example:1.0.0:*:*:*:*:*:*:*"}]}`))
	t.Setenv("GRYPE_FIXTURE", write("grype.json", `{"matches":[{"vulnerability":{"id":"CVE-TEST","severity":"Critical","description":"test finding","fix":{"versions":["1.0.1"]}},"relatedVulnerabilities":[{"id":"GHSA-alias"}],"artifact":{"name":"example","version":"1.0.0","type":"binary"}}]}`))
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
	opts.IgnoreURL = write("ignores.json", `{"ignores":[{"id":"GHSA-alias","reason":"reviewed"}]}`)
	out.Reset()
	result, err = RunImage(opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Blocking) != 0 || len(result.Ignored) != 1 {
		t.Fatalf("shared exception was not applied: %+v", result)
	}
	for _, invalid := range []string{`not json`, `{"components":[{"type":"application"}]}`, `{"components":[{"type":"file","name":"example","version":"1.0.0","cpe":"cpe:2.3:a:vendor:example:1.0.0:*:*:*:*:*:*:*"}]}`, `{"components":[]}`, `{"components":[{"type":"application","name":"example","version":"1.0.0","cpe":"cpe:2.3:a:vendor:example:2.0.0:*:*:*:*:*:*:*"}]}`} {
		path := write("invalid-sbom.json", invalid)
		t.Setenv("SBOM_FIXTURE", path)
		if _, err := RunImage(opts); err == nil {
			t.Fatal("invalid required inventory passed")
		}
	}
	t.Setenv("SBOM_FIXTURE", filepath.Join(directory, "sbom.json"))
	t.Setenv("BASE_IMAGE_REGISTRY", "mirror.example")
	t.Setenv("EXPECTED_SCANNER", "mirror.example/"+grypeImage)
	t.Setenv("SSL_CERT_FILE", write("ca.pem", "test CA"))
	if _, err := RunImage(opts); err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []string{`not json`, `{}`, `{"matches":[{}]}`} {
		t.Setenv("GRYPE_FIXTURE", write("invalid-grype.json", invalid))
		if _, err := RunImage(opts); err == nil {
			t.Fatal("invalid scanner report passed")
		}
	}
	t.Setenv("GRYPE_FIXTURE", filepath.Join(directory, "grype.json"))
	t.Setenv("TMPDIR", filepath.Join(directory, "missing"))
	if _, err := RunImage(opts); err == nil {
		t.Fatal("missing temp directory passed")
	}
	t.Setenv("TMPDIR", directory)
	for _, failure := range []string{"CREATE_FAILURE", "COPY_NO_FILE", "MISSING_SBOM", "SCANNER_FAILURE"} {
		t.Setenv(failure, "true")
		if _, err := RunImage(opts); err == nil {
			t.Fatalf("%s passed", failure)
		}
		t.Setenv(failure, "")
	}
}

func TestDedupePreservesSeverityAndAliases(t *testing.T) {
	for _, reverse := range []bool{false, true} {
		findings := []Finding{
			{ID: "CVE-test", Ecosystem: "binary", Package: "example", Version: "1", Severity: SeverityLow, Aliases: []string{"GHSA-low"}},
			{ID: "CVE-test", Ecosystem: "binary", Package: "example", Version: "1", Severity: SeverityCritical, Aliases: []string{"GHSA-high"}},
		}
		if reverse {
			slices.Reverse(findings)
		}
		result := dedupeFindings(findings)
		if len(result) != 1 || result[0].Severity != SeverityCritical || !slices.Contains(result[0].Aliases, "GHSA-low") || !slices.Contains(result[0].Aliases, "GHSA-high") {
			t.Fatalf("lost severity or aliases: %+v", result)
		}
	}
}
