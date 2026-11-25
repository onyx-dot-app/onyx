package audit

import (
	"fmt"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/basedigest"
)

func TestNodeImagePins(t *testing.T) {
	refs := []basedigest.Ref{
		{Name: "library/node", Tag: "24", Digest: "sha256:a", Path: "web/Dockerfile", Prefixed: true},
		{Name: "node", Tag: "24.22.3", Digest: "sha256:a", Path: ".devcontainer/Dockerfile"},
		{Name: "node", Tag: "24", Digest: "sha256:a", Path: "web/Dockerfile"},
		{Name: "kindest/node", Digest: "sha256:b"},
		{Name: "dhi.io/node", Tag: "24-dev", Digest: "sha256:c", Path: "action.yml"},
	}
	want := []nodeImagePin{
		{"docker.io/library/node:24@sha256:a", []string{"web/Dockerfile", ".devcontainer/Dockerfile"}},
		{"dhi.io/node:24-dev@sha256:c", []string{"action.yml"}},
	}
	if got := nodeImagePins(refs); !reflect.DeepEqual(got, want) {
		t.Fatalf("pins = %#v, want %#v", got, want)
	}
}

func TestScanNodeImagesPreservesAttributionAndRejectsPartialScans(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	gittest.Git(t, dir, "init", "-q")
	image := func(digit string) string { return "node:24@sha256:" + strings.Repeat(digit, 64) }
	web, first, second := image("a"), image("b"), image("c")
	writeFixture(t, dir, "Dockerfile", "FROM "+web+"\nFROM "+first+"\nFROM "+first+"\nFROM "+second+"\n")
	gittest.Git(t, dir, "add", "Dockerfile")
	original := scanOSImage
	t.Cleanup(func() { scanOSImage = original })
	for _, fail := range []bool{false, true} {
		var scanned []string
		scanOSImage = func(ref string, strict bool) ([]Finding, error) {
			if !strict {
				t.Fatal("scan allowed missing OS packages")
			}
			scanned = append(scanned, ref)
			if fail && ref == second {
				return nil, fmt.Errorf("registry unavailable")
			}
			return []Finding{{ID: "CVE-fixture", Severity: SeverityCritical, Manifest: ref}}, nil
		}
		result, err := ScanNodeImages(web)
		if !slices.Equal(scanned, []string{first, second}) {
			t.Fatalf("scanned %v", scanned)
		}
		if fail {
			if err == nil || result != nil {
				t.Fatalf("partial scan: %+v, %v", result, err)
			}
		} else if err != nil || len(result.Blocking) != 2 || result.Blocking[0].Image != first || result.Blocking[1].Image != second {
			t.Fatalf("lost attribution: %+v, %v", result, err)
		}
	}
}
