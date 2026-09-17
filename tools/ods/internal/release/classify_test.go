package release

// Build routing matrix. The fixture repo holds stable tags v4.9.0, v4.10.0 and
// v4.10.1, so v4.10.1 is the only "latest" tag.
//
//	R1 highest stable tag        -> stable, latest, web + desktop
//	R2 older stable tag          -> stable, not latest
//	R3 beta tag                  -> beta, web, no desktop
//	R4 legacy bare "-beta" tag   -> beta (routing accepts what policy rejects)
//	R5 cloud tag                 -> cloud web image only
//	R6 non-suffix "cloud" name   -> cloud web image (substring match)
//	R7 nightly tag               -> web, no desktop, never a test run
//	R8 branch on workflow_dispatch -> test run
//	R9 branch on push            -> not a test run
//	R10 name with a slash        -> sanitized for Docker

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestClassify_routesTagsToBuilds(t *testing.T) {
	// Precondition: a repo whose highest stable tag is v4.10.1.
	_, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	for _, tag := range []string{"v4.9.0", "v4.10.0", "v4.10.1"} {
		gittest.Git(t, work, "tag", tag, sha)
	}
	t.Chdir(work)

	// Under test and postcondition.
	cases := []struct {
		name  string
		ref   string
		event string
		want  Classification
	}{
		{
			name: "R1 highest stable",
			ref:  "v4.10.1",
			want: Classification{
				BuildDesktop: true, BuildWeb: true,
				IsStable: true, IsLatest: true,
			},
		},
		{
			name: "R2 older stable",
			ref:  "v4.9.0",
			want: Classification{
				BuildDesktop: true, BuildWeb: true,
				IsStable: true,
			},
		},
		{
			name: "R3 beta",
			ref:  "v4.11.0-beta.1",
			want: Classification{
				BuildWeb: true,
				IsBeta:   true, IsBetaStandalone: true,
			},
		},
		{
			name: "R4 legacy bare beta",
			ref:  "v4.11.0-beta",
			want: Classification{
				BuildWeb: true,
				IsBeta:   true, IsBetaStandalone: true,
			},
		},
		{
			name: "R5 cloud",
			ref:  "v4.11.0-cloud.2",
			want: Classification{BuildWebCloud: true, IsCloudTag: true},
		},
		{
			name: "R6 cloud substring",
			ref:  "cloud-experiment",
			want: Classification{BuildWebCloud: true, IsCloudTag: true},
		},
		{
			name: "R7 nightly on workflow_dispatch",
			ref:  "nightly-latest",
			// A nightly is a production tag, so dispatching it is a real run.
			event: "workflow_dispatch",
			want:  Classification{BuildWeb: true},
		},
		{
			name:  "R8 branch on workflow_dispatch",
			ref:   "my-branch",
			event: "workflow_dispatch",
			want:  Classification{BuildWeb: true, IsTestRun: true},
		},
		{
			name: "R9 branch on push",
			ref:  "my-branch",
			want: Classification{BuildWeb: true},
		},
		{
			name: "R10 slash in the name",
			ref:  "release/v4.5",
			want: Classification{BuildWeb: true},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			event := tc.event
			if event == "" {
				event = "push"
			}

			got, err := Classify(tc.ref, "abcdef1234567890", event)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			// The backend, model server, and derived names hold for every
			// case, so the table only spells out what varies.
			want := tc.want
			want.BuildBackend = true
			want.BuildModelServer = true
			want.SanitizedTag = strings.ReplaceAll(tc.ref, "/", "-")
			want.ShortSHA = "abcdef1"

			if got != want {
				t.Errorf("Classify(%q, %q):\n got %+v\nwant %+v", tc.ref, event, got, want)
			}
		})
	}
}

func TestClassification_gitHubOutputRendersEveryKey(t *testing.T) {
	// Precondition: a classification with a mix of set and unset flags.
	c := Classification{
		BuildWeb: true, BuildBackend: true, BuildModelServer: true,
		IsStable: true, IsLatest: true,
		SanitizedTag: "v4.10.1", ShortSHA: "abcdef1",
	}

	// Under test.
	got := c.GitHubOutput()

	// Postcondition: the exact lines deployment.yml appends to $GITHUB_OUTPUT.
	want := strings.Join([]string{
		"build-desktop=false",
		"build-web=true",
		"build-web-cloud=false",
		"build-backend=true",
		"build-model-server=true",
		"is-cloud-tag=false",
		"is-beta=false",
		"is-beta-standalone=false",
		"is-stable=true",
		"is-latest=true",
		"is-test-run=false",
		"sanitized-tag=v4.10.1",
		"short-sha=abcdef1",
		"",
	}, "\n")
	if got != want {
		t.Errorf("got:\n%s\nwant:\n%s", got, want)
	}
}

func TestClassify_shortSHAHandlesAShortInput(t *testing.T) {
	// Precondition: a SHA shorter than the 7 characters image tags use.
	_, work := gittest.InitOriginAndWork(t)
	t.Chdir(work)

	// Under test.
	got, err := Classify("my-branch", "abc", "push")

	// Postcondition: truncation must not panic on a short input.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.ShortSHA != "abc" {
		t.Errorf("expected abc, got %s", got.ShortSHA)
	}
}
