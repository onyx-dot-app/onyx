package s3

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
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

// FetchToFile downloads an S3 object to a local file.
// It first tries an unsigned HTTP request and if that fails,
// tries a signed request using AWS CLI.
func FetchToFile(s3url string, destPath string) error {
	parsed, err := ParseS3URL(s3url)
	if err != nil {
		return err
	}

	// Ensure destination directory exists
	if err := os.MkdirAll(filepath.Dir(destPath), 0755); err != nil {
		return fmt.Errorf("failed to create destination directory: %w", err)
	}

	// Try unsigned HTTP request first
	log.Info("Attempting unsigned download...")
	if err := fetchUnsigned(parsed, destPath); err == nil {
		return nil
	} else {
		log.Debugf("Unsigned download failed: %v", err)
	}

	// Try signed request using AWS CLI
	log.Info("Unsigned download failed, attempting signed download...")
	if err := fetchWithAWSCLI(s3url, destPath); err != nil {
		return fmt.Errorf("failed to download from S3: %w\n\nTo authenticate, run:\n  aws sso login\n\nOr configure AWS credentials with:\n  aws configure sso", err)
	}

	return nil
}

// fetchUnsigned attempts to download the file using an unsigned HTTP request.
func fetchUnsigned(s3url *S3URL, destPath string) (err error) {
	resp, err := http.Get(s3url.HTTPEndpoint())
	if err != nil {
		return fmt.Errorf("HTTP request failed: %w", err)
	}
	defer func() {
		if cerr := resp.Body.Close(); cerr != nil && err == nil {
			err = fmt.Errorf("failed to close response body: %w", cerr)
		}
	}()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, resp.Status)
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

	log.Infof("Downloaded %s via unsigned request", humanizeBytes(written))
	return nil
}

// fetchWithAWSCLI attempts to download the file using AWS CLI.
func fetchWithAWSCLI(s3url string, destPath string) error {
	cmd := exec.Command("aws", "s3", "cp", s3url, destPath)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		_ = os.Remove(destPath) // Clean up partial file
		return err
	}

	// Get file size for logging
	if info, err := os.Stat(destPath); err == nil {
		log.Infof("Downloaded %s via AWS CLI", humanizeBytes(info.Size()))
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
