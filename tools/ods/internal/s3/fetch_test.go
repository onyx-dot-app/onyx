package s3

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	log "github.com/sirupsen/logrus"
)

func TestParseS3URL(t *testing.T) {
	parsed, err := ParseS3URL("s3://my-bucket/coverage/tools-ods/abc.yaml")
	if err != nil {
		t.Fatalf("ParseS3URL failed: %v", err)
	}
	if parsed.Bucket != "my-bucket" {
		t.Errorf("Bucket = %q, want %q", parsed.Bucket, "my-bucket")
	}
	if parsed.Key != "coverage/tools-ods/abc.yaml" {
		t.Errorf("Key = %q, want %q", parsed.Key, "coverage/tools-ods/abc.yaml")
	}

	for _, s3url := range []string{
		"https://my-bucket/key",
		"s3://my-bucket",
		"s3://my-bucket/",
		"s3:///key",
	} {
		if _, err := ParseS3URL(s3url); err == nil {
			t.Errorf("ParseS3URL(%q) succeeded, want an error", s3url)
		}
	}
}

func TestSanitizeKeySegment(t *testing.T) {
	for segment, want := range map[string]string{
		"tools/ods":   "tools-ods",
		"release/2.5": "release-2.5",
		"main":        "main",
	} {
		if got := SanitizeKeySegment(segment); got != want {
			t.Errorf("SanitizeKeySegment(%q) = %q, want %q", segment, got, want)
		}
	}
}

func TestFetchUnsigned_writesTheBody(t *testing.T) {
	body := "coverage: 100\n"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := w.Write([]byte(body)); err != nil {
			t.Errorf("failed to write the test response: %v", err)
		}
	}))
	defer server.Close()

	destPath := filepath.Join(t.TempDir(), "snapshot.yaml")
	if err := fetchUnsigned(server.URL, destPath, log.Debugf); err != nil {
		t.Fatalf("fetchUnsigned failed: %v", err)
	}

	written, err := os.ReadFile(destPath)
	if err != nil {
		t.Fatalf("failed to read the downloaded file: %v", err)
	}
	if string(written) != body {
		t.Fatalf("downloaded %q, want %q", written, body)
	}
}

func TestFetchUnsigned_reportsANon200Status(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	}))
	defer server.Close()

	destPath := filepath.Join(t.TempDir(), "snapshot.yaml")
	err := fetchUnsigned(server.URL, destPath, log.Debugf)

	var statusErr *HTTPStatusError
	if !errors.As(err, &statusErr) {
		t.Fatalf("fetchUnsigned error = %v, want an *HTTPStatusError", err)
	}
	if statusErr.StatusCode != http.StatusForbidden {
		t.Errorf("StatusCode = %d, want %d", statusErr.StatusCode, http.StatusForbidden)
	}
	if _, err := os.Stat(destPath); !os.IsNotExist(err) {
		t.Errorf("a file was left at %s, want none", destPath)
	}
}

// A missing object, a refused one, and a missing credential all mean the
// caller has nothing to read, and must not look like a broken download.
func TestUnavailable(t *testing.T) {
	cliAbsent := &exec.Error{Name: "aws", Err: exec.ErrNotFound}
	cliFailed := errors.New("exit status 1")
	forbidden := &HTTPStatusError{StatusCode: http.StatusForbidden, Status: "403 Forbidden"}
	for name, tc := range map[string]struct {
		unsigned  error
		cli       error
		cliOutput string
		want      bool
	}{
		"missing key, no cli":    {&HTTPStatusError{StatusCode: http.StatusNotFound}, cliAbsent, "", true},
		"refused, no credential": {forbidden, cliFailed, "fatal error: Unable to locate credentials", true},
		"refused, missing key":   {forbidden, cliFailed, "fatal error: An error occurred (404) when calling the HeadObject operation: Not Found", true},
		"refused, forbidden":     {forbidden, cliFailed, "fatal error: An error occurred (403) when calling the HeadObject operation: Forbidden", true},
		"refused, bad request":   {forbidden, cliFailed, "fatal error: An error occurred (400) when calling the HeadObject operation: Bad Request", false},
		"server error":           {&HTTPStatusError{StatusCode: http.StatusInternalServerError}, cliFailed, "An error occurred (404)", false},
		"network failure":        {errors.New("HTTP request failed: dial tcp: no route to host"), cliAbsent, "", false},
	} {
		t.Run(name, func(t *testing.T) {
			if got := unavailable(tc.unsigned, tc.cli, tc.cliOutput); got != tc.want {
				t.Fatalf("unavailable = %v, want %v", got, tc.want)
			}
		})
	}
}
