package release

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func testClient(apiHandler, rawHandler http.Handler) (*Client, func()) {
	api := httptest.NewServer(apiHandler)
	raw := httptest.NewServer(rawHandler)
	c := &Client{
		HTTP:       &http.Client{Timeout: 2 * time.Second},
		APIBase:    api.URL,
		RawBase:    raw.URL,
		RetryDelay: time.Millisecond,
	}
	return c, func() { api.Close(); raw.Close() }
}

func TestLatestAppTagHappyPath(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/repos/onyx-dot-app/onyx/releases/latest", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"tag_name": "v4.4.6"}`))
	})
	c, done := testClient(mux, http.NotFoundHandler())
	defer done()

	tag, err := c.LatestAppTag(context.Background())
	if err != nil {
		t.Fatalf("LatestAppTag: %v", err)
	}
	if tag != "v4.4.6" {
		t.Fatalf("got %q", tag)
	}
}

// TestLatestAppTagSkipsToolReleases is the regression test for the repo-global
// /releases/latest endpoint returning a non-app release (e.g. cli/v1.2.3):
// the client must fall back to scanning the release list for an app tag.
func TestLatestAppTagSkipsToolReleases(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/repos/onyx-dot-app/onyx/releases/latest", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"tag_name": "cli/v1.2.3"}`))
	})
	mux.HandleFunc("/repos/onyx-dot-app/onyx/releases", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`[
			{"tag_name": "cli/v1.2.3", "draft": false, "prerelease": false},
			{"tag_name": "v4.5.0-beta.1", "draft": false, "prerelease": true},
			{"tag_name": "v9.9.9", "draft": true, "prerelease": false},
			{"tag_name": "v4.4.6", "draft": false, "prerelease": false}
		]`))
	})
	c, done := testClient(mux, http.NotFoundHandler())
	defer done()

	tag, err := c.LatestAppTag(context.Background())
	if err != nil {
		t.Fatalf("LatestAppTag: %v", err)
	}
	if tag != "v4.4.6" {
		t.Fatalf("got %q, want the newest non-draft, non-prerelease app tag", tag)
	}
}

func TestLatestAppTagFailsWhenUnreachable(t *testing.T) {
	c, done := testClient(http.NotFoundHandler(), http.NotFoundHandler())
	defer done()
	if _, err := c.LatestAppTag(context.Background()); err == nil {
		t.Fatal("expected error when the API is unreachable")
	}
}

func TestFetchFileSuccessAndPath(t *testing.T) {
	var gotPath string
	raw := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		_, _ = w.Write([]byte("IMAGE_TAG=latest\n"))
	})
	c, done := testClient(http.NotFoundHandler(), raw)
	defer done()

	data, err := c.FetchFile(context.Background(), "v4.4.6", "deployment/docker_compose/env.template")
	if err != nil {
		t.Fatalf("FetchFile: %v", err)
	}
	if string(data) != "IMAGE_TAG=latest\n" {
		t.Fatalf("got %q", data)
	}
	want := "/onyx-dot-app/onyx/v4.4.6/deployment/docker_compose/env.template"
	if gotPath != want {
		t.Fatalf("fetched %s, want %s", gotPath, want)
	}
}

func TestFetchFile404DoesNotRetry(t *testing.T) {
	calls := 0
	raw := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		http.NotFound(w, r)
	})
	c, done := testClient(http.NotFoundHandler(), raw)
	defer done()

	if _, err := c.FetchFile(context.Background(), "v0.0.0", "deployment/nope"); err == nil {
		t.Fatal("expected error")
	}
	if calls != 1 {
		t.Fatalf("404 was retried %d times", calls)
	}
}

func TestFetchFileRetriesServerErrors(t *testing.T) {
	calls := 0
	raw := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls < 3 {
			w.WriteHeader(http.StatusBadGateway)
			return
		}
		_, _ = w.Write([]byte("ok"))
	})
	c, done := testClient(http.NotFoundHandler(), raw)
	defer done()

	data, err := c.FetchFile(context.Background(), "main", "deployment/docker_compose/README.md")
	if err != nil {
		t.Fatalf("FetchFile: %v", err)
	}
	if string(data) != "ok" || calls != 3 {
		t.Fatalf("got %q after %d calls", data, calls)
	}
}

func TestConfigRef(t *testing.T) {
	cases := map[string]string{
		"edge":   "main",
		"latest": "main",
		"v4.4.6": "v4.4.6",
		"main":   "main",
	}
	for tag, want := range cases {
		if got := ConfigRef(tag); got != want {
			t.Errorf("ConfigRef(%q) = %q, want %q", tag, got, want)
		}
	}
	if !IsFloatingTag("edge") || !IsFloatingTag("latest") || IsFloatingTag("v4.4.6") {
		t.Error("IsFloatingTag misclassifies")
	}
}
