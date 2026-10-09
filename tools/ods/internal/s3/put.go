package s3

import (
	"fmt"
	"os"
	"os/exec"

	log "github.com/sirupsen/logrus"
)

// PutFile uploads a single local file to an S3 object using the AWS CLI.
// This is equivalent to: aws s3 cp <srcPath> <s3url>
//
// Unlike downloads, uploads have no unsigned fallback and always require AWS
// credentials.
func PutFile(srcPath string, s3url string) error {
	if _, err := ParseS3URL(s3url); err != nil {
		return err
	}

	log.Infof("Uploading %s to %s ...", srcPath, s3url)
	cmd := exec.Command("aws", "s3", "cp", srcPath, s3url)
	// Keep transfer progress off stdout so it can't corrupt a report a caller is
	// capturing from our stdout (see fetch.go).
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("aws s3 cp failed: %w\n\nTo authenticate, run:\n  aws sso login\n\nOr configure AWS credentials with:\n  aws configure sso", err)
	}

	return nil
}
