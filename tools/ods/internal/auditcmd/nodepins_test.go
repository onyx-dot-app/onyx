package auditcmd

import (
	"reflect"
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
