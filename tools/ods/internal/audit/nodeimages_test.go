package audit

import (
	"fmt"

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

func TestCollectNodePackagesPreservesAttributionAndReportsFailures(t *testing.T) {
	webDigest := "sha256:" + strings.Repeat("a", 64)
	first, second := "node:24@first", "node:24@second"
	pins := []nodeImagePin{{Image: "node:24@" + webDigest}, {Image: first}, {Image: second}}
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
		result := &Result{}
		err := collectNodePackages(result, pins, webDigest)
		if !slices.Equal(scanned, []string{first, second}) {
			t.Fatalf("scanned %v", scanned)
		}
		if fail {
			if err == nil {
				t.Fatalf("partial scan: %+v, %v", result, err)
			}
		} else if err != nil || len(result.Blocking) != 2 || result.Blocking[0].Image != first || result.Blocking[1].Image != second {
			t.Fatalf("lost attribution: %+v, %v", result, err)
		}
	}
}
