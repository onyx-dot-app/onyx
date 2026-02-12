package s3

import (
	"fmt"
	"os"
	"os/exec"

	log "github.com/sirupsen/logrus"
)

// SyncDown downloads an S3 prefix to a local directory using AWS CLI.
// This is equivalent to: aws s3 sync <s3url> <destDir>
func SyncDown(s3url string, destDir string) error {
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return fmt.Errorf("failed to create destination directory: %w", err)
	}

	log.Infof("Downloading from %s to %s ...", s3url, destDir)
	cmd := exec.Command("aws", "s3", "sync", s3url, destDir)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("aws s3 sync failed: %w\n\nTo authenticate, run:\n  aws sso login\n\nOr configure AWS credentials with:\n  aws configure sso", err)
	}

	return nil
}

// SyncUp uploads a local directory to an S3 prefix using AWS CLI.
// If delete is true, files in S3 that don't exist locally are removed.
// This is equivalent to: aws s3 sync <srcDir> <s3url> [--delete]
func SyncUp(srcDir string, s3url string, delete bool) error {
	args := []string{"s3", "sync", srcDir, s3url}
	if delete {
		args = append(args, "--delete")
	}

	log.Infof("Uploading from %s to %s ...", srcDir, s3url)
	cmd := exec.Command("aws", args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("aws s3 sync failed: %w\n\nTo authenticate, run:\n  aws sso login\n\nOr configure AWS credentials with:\n  aws configure sso", err)
	}

	return nil
}
