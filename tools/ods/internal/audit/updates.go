package audit

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/s3"
)

const DefaultUpdatePolicyURL = "s3://onyx-internal-tools/audit/updates.json"

// UpdatePolicy records first observations separately from vulnerability exceptions.
// Numeric dotted versions are supported; other version schemes need an explicit comparator.
type UpdatePolicy map[string]PackageUpdates
type PackageUpdates struct {
	CheckedAt time.Time            `json:"checked_at"`
	Minimum   string               `json:"minimum"`
	Releases  map[string]time.Time `json:"releases"`
}

type UpdateStatus struct {
	Package  string `json:"package"`
	Version  string `json:"version"`
	Message  string `json:"message"`
	Warning  bool   `json:"warning"`
	Blocking bool   `json:"blocking"`
}

func numericVersion(value string) ([]uint64, error) {
	parts := strings.Split(value, ".")
	result := make([]uint64, len(parts))
	for i, part := range parts {
		if part == "" || strings.Trim(part, "0123456789") != "" {
			return nil, fmt.Errorf("invalid numeric version %q", value)
		}
		n, err := strconv.ParseUint(part, 10, 64)
		if err != nil {
			return nil, err
		}
		result[i] = n
	}
	return result, nil
}
func compareNumericVersions(a, b string) (int, error) {
	av, err := numericVersion(a)
	if err != nil {
		return 0, err
	}
	bv, err := numericVersion(b)
	if err != nil {
		return 0, err
	}
	for i := 0; i < max(len(av), len(bv)); i++ {
		var x, y uint64
		if i < len(av) {
			x = av[i]
		}
		if i < len(bv) {
			y = bv[i]
		}
		if x < y {
			return -1, nil
		}
		if x > y {
			return 1, nil
		}
	}
	return 0, nil
}

func ReadUpdatePolicy(location string) (UpdatePolicy, error) {
	if strings.HasPrefix(location, "s3://") {
		file, err := os.CreateTemp("", "ods-updates-*")
		if err != nil {
			return nil, err
		}
		path := file.Name()
		_ = file.Close()
		defer func() { _ = os.Remove(path) }()
		if err := s3.FetchToFile(location, path); err != nil {
			return nil, err
		}
		location = path
	}
	data, err := os.ReadFile(location)
	if err != nil {
		return nil, err
	}
	var policy UpdatePolicy
	if err := json.Unmarshal(data, &policy); err != nil {
		return nil, err
	}
	if len(policy) == 0 {
		return nil, fmt.Errorf("update policy is empty")
	}
	return policy, nil
}

// ObserveUpdate preserves each release's first observation across retries and newer releases.
func ObserveUpdate(previous PackageUpdates, version, minimum string, now time.Time) (PackageUpdates, error) {
	if _, err := numericVersion(version); err != nil {
		return previous, err
	}
	if minimum == "" {
		minimum = previous.Minimum
	}
	if _, err := numericVersion(minimum); err != nil {
		return previous, err
	}
	if previous.Minimum != "" {
		cmp, err := compareNumericVersions(minimum, previous.Minimum)
		if err != nil {
			return previous, err
		}
		if cmp < 0 {
			return previous, fmt.Errorf("minimum cannot decrease")
		}
	}
	if previous.CheckedAt.After(now) {
		return previous, fmt.Errorf("observation time moved backwards")
	}
	result := PackageUpdates{CheckedAt: now, Minimum: minimum, Releases: map[string]time.Time{}}
	for release, seen := range previous.Releases {
		cmp, err := compareNumericVersions(version, release)
		if err != nil {
			return previous, err
		}
		if cmp < 0 {
			return previous, fmt.Errorf("upstream version moved backwards")
		}
		if seen.IsZero() || seen.After(previous.CheckedAt) {
			return previous, fmt.Errorf("invalid observation time")
		}
		result.Releases[release] = seen
	}
	if _, ok := result.Releases[version]; !ok {
		result.Releases[version] = now
	}
	return result, nil
}

func CheckUpdate(name, installed string, policy PackageUpdates, now time.Time) (UpdateStatus, error) {
	status := UpdateStatus{Package: name, Version: installed}
	if policy.CheckedAt.IsZero() || policy.CheckedAt.After(now) || len(policy.Releases) == 0 {
		return status, fmt.Errorf("invalid update observation for %s", name)
	}
	cmp, err := compareNumericVersions(installed, policy.Minimum)
	if err != nil {
		return status, err
	}
	if cmp < 0 {
		status.Blocking = true
		status.Warning = true
		status.Message = "below emergency minimum " + policy.Minimum
	}
	var oldest time.Time
	for release, seen := range policy.Releases {
		cmp, err := compareNumericVersions(release, installed)
		if err != nil {
			return status, err
		}
		if seen.IsZero() || seen.After(policy.CheckedAt) {
			return status, fmt.Errorf("invalid release observation for %s", name)
		}
		if cmp > 0 && (oldest.IsZero() || seen.Before(oldest)) {
			oldest = seen
		}
	}
	if !oldest.IsZero() {
		age := now.Sub(oldest)
		status.Warning = status.Warning || age >= 24*time.Hour
		status.Blocking = status.Blocking || age >= 72*time.Hour
		status.Message += "; update due " + oldest.Add(72*time.Hour).Format(time.RFC3339)
	}
	if now.Sub(policy.CheckedAt) >= 24*time.Hour {
		status.Warning = true
		status.Message += "; observation is over 24 hours old; recorded deadlines still apply"
	}
	status.Message = strings.TrimPrefix(status.Message, "; ")
	return status, nil
}

// BlockingUpdates counts maintenance failures without assigning CVE severity.
func (r *Result) BlockingUpdates() int {
	count := 0
	for _, status := range r.Updates {
		if status.Blocking {
			count++
		}
	}
	return count
}
