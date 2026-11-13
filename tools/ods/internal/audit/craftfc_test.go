package audit

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testArtifactsDockerfile = `# syntax=docker/dockerfile:1
ARG BASE_IMAGE_REGISTRY=docker.io
ARG KERNEL_TAG=microvm-kernel-6.18.25-57.115.amzn2023
ARG FC_VERSION=v1.17.0
FROM scratch
ARG KERNEL_TAG
ARG FC_VERSION
`

func writeArtifactsDockerfile(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "Dockerfile.artifacts")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestReadCraftFCPins(t *testing.T) {
	pins, err := ReadCraftFCPins(writeArtifactsDockerfile(t, testArtifactsDockerfile))
	if err != nil {
		t.Fatal(err)
	}
	want := CraftFCPins{KernelPackage: "kernel6.18", KernelVersion: "6.18.25-57.115.amzn2023", FirecrackerVersion: "1.17.0"}
	if pins != want {
		t.Fatalf("got %+v, want %+v", pins, want)
	}
}

func TestReadCraftFCPinsRejectsUnknownKernelTag(t *testing.T) {
	content := strings.Replace(testArtifactsDockerfile, "microvm-kernel-6.18.25-57.115.amzn2023", "v6.18.25", 1)
	if _, err := ReadCraftFCPins(writeArtifactsDockerfile(t, content)); err == nil {
		t.Fatal("expected an error for a kernel tag that is not a microvm-kernel tag")
	}
}

func TestVersionInRange(t *testing.T) {
	cases := []struct {
		version, rng string
		want         bool
	}{
		// The ranges of the published Firecracker advisories.
		{"1.17.0", ">= 0.23.0, <= 1.16.1", false},
		{"1.16.1", ">= 0.23.0, <= 1.16.1", true},
		{"0.22.9", ">= 0.23.0, <= 1.16.1", false},
		{"1.17.0", ">=1.13.0, <= 1.14.3, 1.15.0", false},
		{"1.14.0", ">=1.13.0, <= 1.14.3, 1.15.0", true},
		{"1.15.0", ">=1.13.0, <= 1.14.3, 1.15.0", true},
		{"1.15.1", ">=1.13.0, <= 1.14.3, 1.15.0", false},
		{"1.13.0", "< v1.13.1", true},
		{"1.17.0", "< v1.13.1", false},
		{"1.14.0", "v1.14.0", true},
		{"1.17.0", "v1.14.0", false},
		// An open lower bound runs on.
		{"1.17.0", ">= 1.16.0", true},
		{"1.15.9", "> 1.16.0", false},
		// A range it cannot read is reported for a person to check.
		{"1.17.0", "all versions", true},
		{"1.17.0", "", true},
	}
	for _, tc := range cases {
		if got := versionInRange(tc.version, tc.rng); got != tc.want {
			t.Errorf("versionInRange(%q, %q) = %v, want %v", tc.version, tc.rng, got, tc.want)
		}
	}
}

func TestCompareNumeric(t *testing.T) {
	if compareNumeric("6.18.56-126.188.amzn2023", "6.18.25-57.115.amzn2023") <= 0 {
		t.Fatal("6.18.56-126.188 must be newer than 6.18.25-57.115")
	}
	if compareNumeric("6.18.25-57.115.amzn2023", "6.18.25-57.115.amzn2023") != 0 {
		t.Fatal("equal versions must compare equal")
	}
	if compareNumeric("6.18.25-57.99.amzn2023", "6.18.25-57.115.amzn2023") >= 0 {
		t.Fatal("57.99 must be older than 57.115")
	}
}

// craftFCFeeds serves an ALAS feed with an older, a newer and an unrelated
// advisory, and two Firecracker advisories split over two pages.
func craftFCFeeds(t *testing.T) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	var srv *httptest.Server
	mux.HandleFunc("/alas.rss", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = fmt.Fprintf(w, `<?xml version="1.0"?><rss><channel>
<item><title>ALAS2023-2026-0001 (important): kernel6.18</title><description>CVE-2026-1, CVE-2026-2</description><link>%[1]s/old.html</link></item>
<item><title>ALAS2023-2026-0002 (critical): kernel6.18, kernel6.18-livepatch</title><description>CVE-2026-3</description><link>%[1]s/new.html</link></item>
<item><title>ALAS2023-2026-0003 (critical): kernel6.12</title><description>CVE-2026-4</description><link>%[1]s/missing.html</link></item>
</channel></rss>`, srv.URL)
	})
	mux.HandleFunc("/old.html", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = fmt.Fprint(w, `<td>kernel6.18-6.18.20-50.100.amzn2023.x86_64</td>`)
	})
	mux.HandleFunc("/new.html", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = fmt.Fprint(w, `<td>kernel6.18-6.18.56-126.188.amzn2023.aarch64</td><td>kernel6.18-6.18.56-126.188.amzn2023.x86_64</td>`)
	})
	mux.HandleFunc("/advisories", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("page") == "2" {
			_, _ = fmt.Fprint(w, `[{"ghsa_id":"GHSA-new","cve_id":"CVE-2026-9","severity":"high","summary":"guest escape","html_url":"https://example.test/GHSA-new","vulnerabilities":[{"package":{"name":"Firecracker"},"vulnerable_version_range":">= 1.17.0, < 1.17.1","patched_versions":"1.17.1"}]}]`)
			return
		}
		w.Header().Set("Link", fmt.Sprintf(`<%s/advisories?page=2>; rel="next"`, srv.URL))
		_, _ = fmt.Fprint(w, `[{"ghsa_id":"GHSA-old","severity":"high","vulnerabilities":[{"package":{"name":"Firecracker"},"vulnerable_version_range":">= 0.23.0, <= 1.16.1","patched_versions":"1.16.2, 1.17.0"}]}]`)
	})
	srv = httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func TestRunCraftFC(t *testing.T) {
	srv := craftFCFeeds(t)
	var stdout, stderr bytes.Buffer
	result, err := RunCraftFC(CraftFCOptions{
		Dockerfile:               writeArtifactsDockerfile(t, testArtifactsDockerfile),
		FirecrackerAdvisoriesURL: srv.URL + "/advisories",
		ALASFeedURL:              srv.URL + "/alas.rss",
		Format:                   "json",
		FailOn:                   SeverityCritical,
		Stdout:                   &stdout,
		Stderr:                   &stderr,
	})
	if err != nil {
		t.Fatal(err)
	}

	var ids []string
	for _, f := range result.Findings {
		ids = append(ids, f.ID)
		if f.Ecosystem != EcosystemCraftFC || f.Source != SourceCraftFC {
			t.Errorf("%s: ecosystem %q source %q", f.ID, f.Ecosystem, f.Source)
		}
	}
	if strings.Join(ids, ",") != "ALAS2023-2026-0002,GHSA-new" {
		t.Fatalf("findings = %v, want the newer kernel advisory and the Firecracker advisory on page 2", ids)
	}
	kernel := result.Findings[0]
	if kernel.FixedIn != "6.18.56-126.188.amzn2023" || kernel.Severity != SeverityCritical || strings.Join(kernel.Aliases, ",") != "CVE-2026-3" {
		t.Errorf("kernel finding = %+v", kernel)
	}
	if len(result.Blocking) != 1 || result.Blocking[0].ID != "ALAS2023-2026-0002" {
		t.Errorf("blocking = %+v, want only the critical kernel advisory", result.Blocking)
	}

	var report Result
	if err := json.Unmarshal(stdout.Bytes(), &report); err != nil {
		t.Fatalf("json report: %v\n%s", err, stdout.String())
	}
	if len(report.ScannedPackages) != 2 {
		t.Errorf("scanned packages = %+v, want kernel6.18 and firecracker", report.ScannedPackages)
	}
}

func TestRunCraftFCFailsWhenAFeedFails(t *testing.T) {
	srv := craftFCFeeds(t)
	_, err := RunCraftFC(CraftFCOptions{
		Dockerfile:               writeArtifactsDockerfile(t, testArtifactsDockerfile),
		FirecrackerAdvisoriesURL: srv.URL + "/advisories",
		ALASFeedURL:              srv.URL + "/missing.rss",
		Format:                   "json",
		FailOn:                   SeverityCritical,
		Stdout:                   &bytes.Buffer{},
		Stderr:                   &bytes.Buffer{},
	})
	if err == nil || !strings.Contains(err.Error(), "HTTP 404") {
		t.Fatalf("err = %v, want the failed feed read", err)
	}
}

func TestKernelFindingsFailsWhenThePageNamesNoPackage(t *testing.T) {
	mux := http.NewServeMux()
	var srv *httptest.Server
	mux.HandleFunc("/alas.rss", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = fmt.Fprintf(w, `<rss><channel><item><title>ALAS2023-2026-0009 (important): kernel6.18</title><link>%s/empty.html</link></item></channel></rss>`, srv.URL)
	})
	mux.HandleFunc("/empty.html", func(w http.ResponseWriter, _ *http.Request) { _, _ = fmt.Fprint(w, "<html></html>") })
	srv = httptest.NewServer(mux)
	defer srv.Close()

	pins := CraftFCPins{KernelPackage: "kernel6.18", KernelVersion: "6.18.25-57.115.amzn2023", FirecrackerVersion: "1.17.0"}
	if _, err := kernelFindings(srv.Client(), srv.URL+"/alas.rss", pins); err == nil {
		t.Fatal("expected an error when an advisory page names no fixed package")
	}
}
