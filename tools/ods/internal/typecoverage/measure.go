// Package typecoverage measures TypeScript type coverage for web/ and groups
// it into a coverage.Profile, so the coverage gate can hold it against a
// baseline.
package typecoverage

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"sort"
	"strings"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

// Depth is how many leading directory names make up a report row, e.g.
// "src/app/admin". Changing it renames the rows, so regenerate the baseline.
const Depth = 3

// FileCount is the measurement for one file, as web/tools/type-check
// writes it.
type FileCount struct {
	// File is the path relative to web/, with forward slashes.
	File string `json:"file"`
	// Correct is the number of identifiers whose type is not `any`.
	Correct int `json:"correct"`
	// Total is the number of identifiers in the file.
	Total int `json:"total"`
}

type measurement struct {
	Files []FileCount `json:"files"`
}

// Parse reads the JSON that web/tools/type-check writes.
func Parse(r io.Reader) ([]FileCount, error) {
	decoder := json.NewDecoder(r)
	decoder.DisallowUnknownFields()

	var m measurement
	if err := decoder.Decode(&m); err != nil {
		return nil, fmt.Errorf("parse type coverage: %w", err)
	}
	// Zero files means the script looked in the wrong place, not that web/
	// is fully typed.
	if len(m.Files) == 0 {
		return nil, errors.New("parse type coverage: no files were measured")
	}
	for _, f := range m.Files {
		if f.File == "" {
			return nil, errors.New("parse type coverage: a file has no path")
		}
		if f.Total < 0 || f.Correct < 0 || f.Correct > f.Total {
			return nil, fmt.Errorf("parse type coverage: %s has %d of %d identifiers typed", f.File, f.Correct, f.Total)
		}
	}
	return m.Files, nil
}

// ParseFile parses the measurement at the given path.
func ParseFile(measurementPath string) ([]FileCount, error) {
	f, err := os.Open(measurementPath)
	if err != nil {
		return nil, fmt.Errorf("open type coverage: %w", err)
	}
	defer func() { _ = f.Close() }()
	return Parse(f)
}

// Aggregate groups files into directories at most depth names deep. A file
// in a shallower directory counts toward that directory, and a file at the
// root of web/ counts toward ".".
func Aggregate(files []FileCount, depth int) *coverage.Profile {
	byDir := make(map[string]*coverage.PackageCoverage)
	for _, f := range files {
		name := rowName(f.File, depth)
		row, ok := byDir[name]
		if !ok {
			row = &coverage.PackageCoverage{Package: name}
			byDir[name] = row
		}
		row.Covered += f.Correct
		row.Total += f.Total
	}

	profile := &coverage.Profile{Packages: make([]coverage.PackageCoverage, 0, len(byDir))}
	for _, row := range byDir {
		profile.Packages = append(profile.Packages, *row)
	}
	sort.Slice(profile.Packages, func(i, j int) bool {
		return profile.Packages[i].Package < profile.Packages[j].Package
	})
	return profile
}

func rowName(file string, depth int) string {
	dir := path.Dir(file)
	if dir == "." {
		return dir
	}
	names := strings.Split(dir, "/")
	if len(names) > depth {
		names = names[:depth]
	}
	return strings.Join(names, "/")
}
