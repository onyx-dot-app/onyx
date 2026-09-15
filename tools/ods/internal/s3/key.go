package s3

import "strings"

// SanitizeKeySegment turns a git ref or a repository path into one S3 key
// segment. Slashes become dashes, so "release/2.5" is "release-2.5" and
// "tools/ods" is "tools-ods".
func SanitizeKeySegment(segment string) string {
	return strings.ReplaceAll(segment, "/", "-")
}
