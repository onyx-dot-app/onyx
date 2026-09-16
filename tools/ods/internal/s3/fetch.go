package s3

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	log "github.com/sirupsen/logrus"
)

// S3URL represents a parsed S3 URL.
type S3URL struct {
	Bucket string
	Key    string
}

// ParseS3URL parses an s3:// URL into bucket and key components.
func ParseS3URL(s3url string) (*S3URL, error) {
	if !strings.HasPrefix(s3url, "s3://") {
		return nil, fmt.Errorf("invalid S3 URL: must start with s3://")
	}

	path := strings.TrimPrefix(s3url, "s3://")
	parts := strings.SplitN(path, "/", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return nil, fmt.Errorf("invalid S3 URL: must be s3://bucket/key")
	}

	return &S3URL{
		Bucket: parts[0],
		Key:    parts[1],
	}, nil
}

// HTTPEndpoint returns the HTTP endpoint for unsigned access.
func (s *S3URL) HTTPEndpoint() string {
	return fmt.Sprintf("https://%s.s3.amazonaws.com/%s", s.Bucket, s.Key)
}

// logFunc writes a progress line. FetchToFile uses log.Infof; the quiet
// variant uses log.Debugf.
type logFunc func(format string, args ...any)

// HTTPStatusError reports an unsigned GET that S3 answered with a non-200 status.
type HTTPStatusError struct {
	StatusCode int
	Status     string
}

func (e *HTTPStatusError) Error() string {
	return fmt.Sprintf("HTTP %d: %s", e.StatusCode, e.Status)
}

// ErrObjectUnavailable marks a download that failed because the object cannot
// be read as the caller stands: it does not exist, or reading it needs
// credentials the caller does not hold. Any other failure is a real problem.
var ErrObjectUnavailable = errors.New("object unavailable")

// unavailableCLIOutput matches how the aws CLI reports a missing or refused
// object, and missing credentials. A HeadObject answer carries no error body,
// so the CLI reports the HTTP status.
var unavailableCLIOutput = regexp.MustCompile(`An error occurred \((403|404)\)|Unable to locate credentials`)

// unavailable reports whether both failed attempts say the object cannot be
// read as the caller stands, rather than that something is broken. The
// unsigned answer must be 403 or 404: without ListBucket permission a missing
// key also gets 403. Then the aws CLI must be absent, or report a 403, a 404,
// or no credentials.
func unavailable(unsignedErr, cliErr error, cliOutput string) bool {
	var status *HTTPStatusError
	if !errors.As(unsignedErr, &status) {
		return false
	}
	if status.StatusCode != http.StatusForbidden && status.StatusCode != http.StatusNotFound {
		return false
	}
	if errors.Is(cliErr, exec.ErrNotFound) {
		return true
	}
	return unavailableCLIOutput.MatchString(cliOutput)
}

// FetchToFile downloads an S3 object to a local file.
// It first tries an unsigned HTTP request and if that fails,
// tries a signed request using AWS CLI.
func FetchToFile(s3url string, destPath string) error {
	return fetch(s3url, destPath, false)
}

// FetchToFileQuiet downloads an S3 object like FetchToFile but logs only at
// debug level and returns the reasons both attempts failed. Use it to probe
// for an object that is often absent: a failure that means the object cannot
// be read as the caller stands wraps ErrObjectUnavailable.
func FetchToFileQuiet(s3url string, destPath string) error {
	return fetch(s3url, destPath, true)
}

// fetch downloads an S3 object, unsigned first and signed second. quiet keeps
// every line at debug level, captures the aws CLI output, and reports both
// failures to the caller instead of the interactive authentication hint.
func fetch(s3url string, destPath string, quiet bool) error {
	parsed, err := ParseS3URL(s3url)
	if err != nil {
		return err
	}

	// Ensure destination directory exists
	if err := os.MkdirAll(filepath.Dir(destPath), 0755); err != nil {
		return fmt.Errorf("failed to create destination directory: %w", err)
	}

	progress := logFunc(log.Infof)
	if quiet {
		progress = log.Debugf
	}

	// Try unsigned HTTP request first
	progress("Attempting unsigned download...")
	unsignedErr := fetchUnsigned(parsed.HTTPEndpoint(), destPath, progress)
	if unsignedErr == nil {
		return nil
	}
	log.Debugf("Unsigned download failed: %v", unsignedErr)

	// Try signed request using AWS CLI
	progress("Unsigned download failed, attempting signed download...")
	// The CLI's transfer progress ("Completed X/Y ... with N file(s)
	// remaining") must not reach stdout: callers like
	// `ods audit ... --format=sarif` redirect our stdout into a report file,
	// and stray progress lines corrupt it.
	var capturedOutput strings.Builder
	var cliOutput io.Writer = os.Stderr
	if quiet {
		cliOutput = &capturedOutput
	}
	cliErr := fetchWithAWSCLI(s3url, destPath, cliOutput, progress)
	if cliErr == nil {
		return nil
	}

	if quiet {
		reason := fmt.Errorf("failed to download %s: unsigned attempt: %w; aws CLI attempt: %v: %s",
			s3url, unsignedErr, cliErr, strings.TrimSpace(capturedOutput.String()))
		if unavailable(unsignedErr, cliErr, capturedOutput.String()) {
			return fmt.Errorf("%w: %w", ErrObjectUnavailable, reason)
		}
		return reason
	}
	return fmt.Errorf("failed to download from S3: %w\n\nTo authenticate, run:\n  aws sso login\n\nOr configure AWS credentials with:\n  aws configure sso", cliErr)
}

// fetchUnsigned attempts to download the file using an unsigned HTTP request.
// It takes the endpoint as a string so tests can point it at a local server.
func fetchUnsigned(endpoint string, destPath string, progress logFunc) (err error) {
	resp, err := http.Get(endpoint)
	if err != nil {
		return fmt.Errorf("HTTP request failed: %w", err)
	}
	defer func() {
		if cerr := resp.Body.Close(); cerr != nil && err == nil {
			err = fmt.Errorf("failed to close response body: %w", cerr)
		}
	}()

	if resp.StatusCode != http.StatusOK {
		return &HTTPStatusError{StatusCode: resp.StatusCode, Status: resp.Status}
	}

	// Create destination file
	file, err := os.Create(destPath)
	if err != nil {
		return fmt.Errorf("failed to create file: %w", err)
	}
	defer func() {
		if cerr := file.Close(); cerr != nil && err == nil {
			err = fmt.Errorf("failed to close file: %w", cerr)
		}
	}()

	// Copy response body to file
	written, err := io.Copy(file, resp.Body)
	if err != nil {
		_ = os.Remove(destPath) // Clean up partial file
		return fmt.Errorf("failed to write file: %w", err)
	}

	progress("Downloaded %s via unsigned request", humanizeBytes(written))
	return nil
}

// fetchWithAWSCLI attempts to download the file using AWS CLI. Both CLI
// streams go to cliOutput.
func fetchWithAWSCLI(s3url string, destPath string, cliOutput io.Writer, progress logFunc) error {
	cmd := exec.Command("aws", "s3", "cp", s3url, destPath)
	cmd.Stdout = cliOutput
	cmd.Stderr = cliOutput

	if err := cmd.Run(); err != nil {
		_ = os.Remove(destPath) // Clean up partial file
		return err
	}

	// Get file size for logging
	if info, err := os.Stat(destPath); err == nil {
		progress("Downloaded %s via AWS CLI", humanizeBytes(info.Size()))
	}

	return nil
}

// humanizeBytes converts bytes to a human-readable string.
func humanizeBytes(bytes int64) string {
	const unit = 1024
	if bytes < unit {
		return fmt.Sprintf("%d B", bytes)
	}
	div, exp := int64(unit), 0
	for n := bytes / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %cB", float64(bytes)/float64(div), "KMGTPE"[exp])
}
