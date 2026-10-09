package s3

import (
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// fakeAWS puts an aws on PATH that records its arguments, one per line, and
// then runs script. It returns the file the arguments are written to.
func fakeAWS(t *testing.T, script string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake aws is a shell script")
	}
	binDir := t.TempDir()
	argvFile := filepath.Join(binDir, "argv")
	body := "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"${0%/*}/argv\"\n" + script
	if err := os.WriteFile(filepath.Join(binDir, "aws"), []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir)
	return argvFile
}

// awsArgs returns the arguments the fake aws received, or nil if it never ran.
func awsArgs(t *testing.T, argvFile string) []string {
	t.Helper()
	data, err := os.ReadFile(argvFile)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

func assertArgs(t *testing.T, got, want []string) {
	t.Helper()
	if strings.Join(got, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("expected aws args %q, got %q", want, got)
	}
}

func assertAuthHint(t *testing.T, err error) {
	t.Helper()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("expected the aws exit error to be wrapped, got %v", err)
	}
	if !strings.Contains(err.Error(), "aws sso login") {
		t.Fatalf("expected the authentication hint, got %q", err.Error())
	}
}

func statusServer(t *testing.T, status int) string {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
	}))
	t.Cleanup(server.Close)
	return server.URL
}

func TestSyncDown_createsTheDestinationAndSyncsIntoIt(t *testing.T) {
	argvFile := fakeAWS(t, "exit 0\n")
	destDir := filepath.Join(t.TempDir(), "nested", "baselines")

	if err := SyncDown("s3://bucket/baselines/admin/main/", destDir); err != nil {
		t.Fatalf("SyncDown failed: %v", err)
	}

	if info, err := os.Stat(destDir); err != nil || !info.IsDir() {
		t.Fatalf("expected %s to be created as a directory, got %v", destDir, err)
	}
	assertArgs(t, awsArgs(t, argvFile), []string{"s3", "sync", "s3://bucket/baselines/admin/main/", destDir})
}

func TestSyncDown_reportsAFailedSync(t *testing.T) {
	fakeAWS(t, "exit 1\n")

	assertAuthHint(t, SyncDown("s3://bucket/prefix/", t.TempDir()))
}

func TestSyncDown_reportsAnUncreatableDestination(t *testing.T) {
	argvFile := fakeAWS(t, "exit 0\n")
	file := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(file, nil, 0o644); err != nil {
		t.Fatal(err)
	}

	err := SyncDown("s3://bucket/prefix/", filepath.Join(file, "dest"))

	if err == nil || !strings.Contains(err.Error(), "failed to create destination directory") {
		t.Fatalf("expected a directory creation error, got %v", err)
	}
	if args := awsArgs(t, argvFile); args != nil {
		t.Fatalf("expected aws not to run, got %q", args)
	}
}

func TestSyncUp_passesDeleteOnlyWhenAsked(t *testing.T) {
	tests := []struct {
		name   string
		delete bool
		want   []string
	}{
		{"keep", false, []string{"s3", "sync", "shots", "s3://bucket/b/"}},
		{"delete", true, []string{"s3", "sync", "shots", "s3://bucket/b/", "--delete"}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			argvFile := fakeAWS(t, "exit 0\n")

			if err := SyncUp("shots", "s3://bucket/b/", tt.delete); err != nil {
				t.Fatalf("SyncUp failed: %v", err)
			}

			assertArgs(t, awsArgs(t, argvFile), tt.want)
		})
	}
}

func TestSyncUp_reportsAFailedSync(t *testing.T) {
	fakeAWS(t, "exit 2\n")

	assertAuthHint(t, SyncUp("shots", "s3://bucket/b/", false))
}

func TestPutFile_copiesTheFile(t *testing.T) {
	argvFile := fakeAWS(t, "exit 0\n")

	if err := PutFile("snapshot.yaml", "s3://bucket/coverage/abc.yaml"); err != nil {
		t.Fatalf("PutFile failed: %v", err)
	}

	assertArgs(t, awsArgs(t, argvFile), []string{"s3", "cp", "snapshot.yaml", "s3://bucket/coverage/abc.yaml"})
}

func TestPutFile_rejectsAnInvalidURLWithoutCallingAWS(t *testing.T) {
	argvFile := fakeAWS(t, "exit 0\n")

	err := PutFile("snapshot.yaml", "s3://bucket-only")

	if err == nil || !strings.Contains(err.Error(), "invalid S3 URL") {
		t.Fatalf("expected an invalid URL error, got %v", err)
	}
	if args := awsArgs(t, argvFile); args != nil {
		t.Fatalf("expected aws not to run, got %q", args)
	}
}

func TestPutFile_reportsAFailedCopy(t *testing.T) {
	fakeAWS(t, "exit 1\n")

	assertAuthHint(t, PutFile("snapshot.yaml", "s3://bucket/key"))
}

func TestFetchToFile_rejectsAnInvalidURL(t *testing.T) {
	for name, download := range map[string]func(string, string) error{
		"FetchToFile":      FetchToFile,
		"FetchToFileQuiet": FetchToFileQuiet,
	} {
		t.Run(name, func(t *testing.T) {
			argv := fakeAWS(t, "exit 0\n")

			err := download("https://bucket/key", filepath.Join(t.TempDir(), "out"))

			if err == nil || err.Error() != "invalid S3 URL: must start with s3://" {
				t.Fatalf("expected an invalid URL error, got %v", err)
			}
			if args := awsArgs(t, argv); args != nil {
				t.Fatalf("expected aws not to run, got %q", args)
			}
		})
	}
}

func TestFetchFrom_skipsTheCLIWhenTheUnsignedDownloadWorks(t *testing.T) {
	argvFile := fakeAWS(t, "exit 1\n")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("public"))
	}))
	defer server.Close()
	destPath := filepath.Join(t.TempDir(), "nested", "out")

	if err := fetchFrom(server.URL, "s3://bucket/key", destPath, false); err != nil {
		t.Fatalf("fetchFrom failed: %v", err)
	}

	if got, _ := os.ReadFile(destPath); string(got) != "public" {
		t.Fatalf("expected %q, got %q", "public", got)
	}
	if args := awsArgs(t, argvFile); args != nil {
		t.Fatalf("expected aws not to run, got %q", args)
	}
}

func TestFetchFrom_fallsBackToTheCLI(t *testing.T) {
	for name, quiet := range map[string]bool{"loud": false, "quiet": true} {
		t.Run(name, func(t *testing.T) {
			argvFile := fakeAWS(t, "printf 'signed' > \"$4\"\n")
			destPath := filepath.Join(t.TempDir(), "out")

			if err := fetchFrom(statusServer(t, http.StatusForbidden), "s3://bucket/key", destPath, quiet); err != nil {
				t.Fatalf("fetchFrom failed: %v", err)
			}

			assertArgs(t, awsArgs(t, argvFile), []string{"s3", "cp", "s3://bucket/key", destPath})
			if got, _ := os.ReadFile(destPath); string(got) != "signed" {
				t.Fatalf("expected %q, got %q", "signed", got)
			}
		})
	}
}

func TestFetchFrom_hintsAtAuthenticationWhenBothAttemptsFail(t *testing.T) {
	fakeAWS(t, "echo 'partial' > \"$4\"; exit 1\n")
	destPath := filepath.Join(t.TempDir(), "out")

	err := fetchFrom(statusServer(t, http.StatusForbidden), "s3://bucket/key", destPath, false)

	assertAuthHint(t, err)
	if errors.Is(err, ErrObjectUnavailable) {
		t.Fatalf("expected the loud variant never to report unavailability, got %v", err)
	}
	if _, statErr := os.Stat(destPath); !os.IsNotExist(statErr) {
		t.Fatalf("expected the partial file to be removed, got %v", statErr)
	}
}

func TestFetchFrom_quietReportsBothFailures(t *testing.T) {
	tests := []struct {
		name            string
		status          int
		script          string
		wantUnavailable bool
		wantInMessage   string
	}{
		{
			name:            "missing object",
			status:          http.StatusNotFound,
			script:          "echo '  fatal error: An error occurred (404) when calling the HeadObject operation  '; exit 1\n",
			wantUnavailable: true,
			wantInMessage:   "aws CLI attempt: exit status 1: fatal error: An error occurred (404) when calling the HeadObject operation",
		},
		{
			name:            "server error",
			status:          http.StatusInternalServerError,
			script:          "echo 'fatal error: An error occurred (404)' >&2; exit 1\n",
			wantUnavailable: false,
			wantInMessage:   "unsigned attempt: HTTP 500: 500 Internal Server Error",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			fakeAWS(t, tt.script)

			err := fetchFrom(statusServer(t, tt.status), "s3://bucket/key", filepath.Join(t.TempDir(), "out"), true)

			if err == nil {
				t.Fatal("expected an error, got nil")
			}
			if got := errors.Is(err, ErrObjectUnavailable); got != tt.wantUnavailable {
				t.Fatalf("expected unavailable=%v, got %v (%v)", tt.wantUnavailable, got, err)
			}
			if !strings.Contains(err.Error(), tt.wantInMessage) {
				t.Fatalf("expected %q in the error, got %q", tt.wantInMessage, err.Error())
			}
			if strings.Contains(err.Error(), "aws sso login") {
				t.Fatalf("expected no authentication hint in quiet mode, got %q", err.Error())
			}
		})
	}
}

func TestFetchFrom_quietTreatsAMissingCLIAsUnavailable(t *testing.T) {
	t.Setenv("PATH", t.TempDir())

	err := fetchFrom(statusServer(t, http.StatusNotFound), "s3://bucket/key", filepath.Join(t.TempDir(), "out"), true)

	if !errors.Is(err, ErrObjectUnavailable) {
		t.Fatalf("expected ErrObjectUnavailable, got %v", err)
	}
}

func TestFetchFrom_reportsAnUncreatableDestination(t *testing.T) {
	file := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(file, nil, 0o644); err != nil {
		t.Fatal(err)
	}

	err := fetchFrom("http://127.0.0.1:0", "s3://bucket/key", filepath.Join(file, "out"), false)

	if err == nil || !strings.Contains(err.Error(), "failed to create destination directory") {
		t.Fatalf("expected a directory creation error, got %v", err)
	}
}

func TestFetchUnsigned_reportsAFailedRequest(t *testing.T) {
	server := httptest.NewServer(http.NotFoundHandler())
	endpoint := server.URL
	server.Close()

	err := fetchUnsigned(endpoint, filepath.Join(t.TempDir(), "out"), t.Logf)

	if err == nil || !strings.HasPrefix(err.Error(), "HTTP request failed:") {
		t.Fatalf("expected a request failure, got %v", err)
	}
	var statusErr *HTTPStatusError
	if errors.As(err, &statusErr) {
		t.Fatalf("expected a transport error, not a status, got %v", err)
	}
}

func TestFetchUnsigned_reportsAnUncreatableFile(t *testing.T) {
	destPath := filepath.Join(t.TempDir(), "missing-dir", "out")

	err := fetchUnsigned(statusServer(t, http.StatusOK), destPath, t.Logf)

	if err == nil || !strings.HasPrefix(err.Error(), "failed to create file:") {
		t.Fatalf("expected a file creation error, got %v", err)
	}
}

func TestFetchUnsigned_removesATruncatedDownload(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, buf, err := w.(http.Hijacker).Hijack()
		if err != nil {
			t.Errorf("hijack failed: %v", err)
			return
		}
		_, _ = buf.WriteString("HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\npartial")
		_ = buf.Flush()
		_ = conn.(*net.TCPConn).Close()
	}))
	defer server.Close()
	destPath := filepath.Join(t.TempDir(), "out")

	err := fetchUnsigned(server.URL, destPath, t.Logf)

	if err == nil || !strings.HasPrefix(err.Error(), "failed to write file:") {
		t.Fatalf("expected a write error, got %v", err)
	}
	if _, statErr := os.Stat(destPath); !os.IsNotExist(statErr) {
		t.Fatalf("expected the partial file to be removed, got %v", statErr)
	}
}
