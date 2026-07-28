package install

import (
	"strings"
	"testing"
)

func TestSetVarReplacesAllUncommentedLines(t *testing.T) {
	in := "IMAGE_TAG=latest\nOTHER=1\nIMAGE_TAG=stale\n"
	out := SetVar(in, "IMAGE_TAG", "v1.2.3")
	if strings.Count(out, "IMAGE_TAG=v1.2.3") != 2 || strings.Contains(out, "latest") {
		t.Fatalf("got %q", out)
	}
}

func TestSetVarAppendsWhenMissing(t *testing.T) {
	out := SetVar("OTHER=1", "IMAGE_TAG", "edge")
	if !strings.HasSuffix(out, "OTHER=1\nIMAGE_TAG=edge\n") {
		t.Fatalf("got %q", out)
	}
}

func TestSetVarDoesNotTouchCommentedLines(t *testing.T) {
	in := "# IMAGE_TAG=old\nIMAGE_TAG=latest\n"
	out := SetVar(in, "IMAGE_TAG", "v1")
	if !strings.Contains(out, "# IMAGE_TAG=old") {
		t.Fatalf("commented line was modified: %q", out)
	}
	if !strings.Contains(out, "IMAGE_TAG=v1\n") {
		t.Fatalf("uncommented line not set: %q", out)
	}
}

func TestSetVarUncommentUncommentsAndSets(t *testing.T) {
	in := "# ENABLE_CRAFT=false\nOTHER=1\n"
	out := SetVarUncomment(in, "ENABLE_CRAFT", "true")
	if !strings.Contains(out, "ENABLE_CRAFT=true") || strings.Contains(out, "# ENABLE_CRAFT") {
		t.Fatalf("got %q", out)
	}

	// Appends when no line matches at all.
	out = SetVarUncomment("OTHER=1\n", "SANDBOX_BACKEND", "docker")
	if !strings.HasSuffix(out, "SANDBOX_BACKEND=docker\n") {
		t.Fatalf("got %q", out)
	}
}

func TestVarStripsQuotesAndSpace(t *testing.T) {
	content := `USER_AUTH_SECRET="abc 123"` + "\nIMAGE_TAG=v1.0.0 \n# IMAGE_TAG=commented\n"
	if got := Var(content, "USER_AUTH_SECRET"); got != "abc123" {
		t.Fatalf("got %q", got)
	}
	if got := Var(content, "IMAGE_TAG"); got != "v1.0.0" {
		t.Fatalf("got %q", got)
	}
	if got := Var(content, "MISSING"); got != "" {
		t.Fatalf("got %q", got)
	}
}

func TestSandboxBackendForTag(t *testing.T) {
	cases := map[string]string{
		"edge":        "docker",
		"latest":      "docker",
		"nightly-x":   "docker",
		"v4.0.6":      "docker",
		"4.0.6":       "docker",
		"v4.1.0":      "docker",
		"v5.0.0":      "docker",
		"v4.0.5":      "kubernetes",
		"v3.9.9":      "kubernetes",
		"v4.0.6-beta": "docker",
		"v4.0.5-beta": "kubernetes",
	}
	for tag, want := range cases {
		if got := sandboxBackendForTag(tag); got != want {
			t.Errorf("sandboxBackendForTag(%q) = %q, want %q", tag, got, want)
		}
	}
}
