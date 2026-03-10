package imgdiff

import (
	"fmt"
	"image"
	"image/color"
	"image/png"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Status represents the comparison status of a screenshot.
type Status int

const (
	// StatusUnchanged means the baseline and current images are identical (within threshold).
	StatusUnchanged Status = iota
	// StatusChanged means the images differ beyond the threshold.
	StatusChanged
	// StatusAdded means the image exists only in the current directory (no baseline).
	StatusAdded
	// StatusRemoved means the image exists only in the baseline directory (no current).
	StatusRemoved
)

// String returns a human-readable string for the status.
func (s Status) String() string {
	switch s {
	case StatusUnchanged:
		return "unchanged"
	case StatusChanged:
		return "changed"
	case StatusAdded:
		return "added"
	case StatusRemoved:
		return "removed"
	default:
		return "unknown"
	}
}

// Result holds the comparison result for a single screenshot.
type Result struct {
	// Name is the filename of the screenshot (e.g. "admin-documents-explorer.png").
	Name string

	// Status is the comparison status.
	Status Status

	// DiffPercent is the percentage of pixels that differ (0.0 to 100.0).
	DiffPercent float64

	// DiffPixels is the number of pixels that differ.
	DiffPixels int

	// TotalPixels is the total number of pixels compared.
	TotalPixels int

	// BaselinePath is the path to the baseline image (empty if added).
	BaselinePath string

	// CurrentPath is the path to the current image (empty if removed).
	CurrentPath string

	// DiffImage is the generated diff overlay image (nil if unchanged, added, or removed).
	DiffImage image.Image
}

// Compare compares two PNG images pixel-by-pixel and returns the result.
// The threshold parameter (0.0 to 1.0) controls per-channel sensitivity:
// a pixel is considered different if any channel differs by more than threshold * 255.
func Compare(baselinePath, currentPath string, threshold float64) (*Result, error) {
	baseline, err := decodePNG(baselinePath)
	if err != nil {
		return nil, fmt.Errorf("failed to decode baseline %s: %w", baselinePath, err)
	}

	current, err := decodePNG(currentPath)
	if err != nil {
		return nil, fmt.Errorf("failed to decode current %s: %w", currentPath, err)
	}

	baselineBounds := baseline.Bounds()
	currentBounds := current.Bounds()

	// Use the larger dimensions to ensure we compare the full area
	width := max(baselineBounds.Dx(), currentBounds.Dx())
	height := max(baselineBounds.Dy(), currentBounds.Dy())
	totalPixels := width * height

	if totalPixels == 0 {
		return &Result{
			Name:         filepath.Base(currentPath),
			Status:       StatusUnchanged,
			BaselinePath: baselinePath,
			CurrentPath:  currentPath,
		}, nil
	}

	diffImage := image.NewRGBA(image.Rect(0, 0, width, height))
	diffPixels := 0
	thresholdValue := threshold * 255.0

	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			// Get pixel from each image (transparent if out of bounds)
			var br, bg, bb, ba uint32
			var cr, cg, cb, ca uint32

			if x < baselineBounds.Dx() && y < baselineBounds.Dy() {
				br, bg, bb, ba = baseline.At(baselineBounds.Min.X+x, baselineBounds.Min.Y+y).RGBA()
			}
			if x < currentBounds.Dx() && y < currentBounds.Dy() {
				cr, cg, cb, ca = current.At(currentBounds.Min.X+x, currentBounds.Min.Y+y).RGBA()
			}

			// Convert from 16-bit to 8-bit
			br8 := float64(br >> 8)
			bg8 := float64(bg >> 8)
			bb8 := float64(bb >> 8)
			ba8 := float64(ba >> 8)
			cr8 := float64(cr >> 8)
			cg8 := float64(cg >> 8)
			cb8 := float64(cb >> 8)
			ca8 := float64(ca >> 8)

			// Check if channels differ beyond threshold
			isDiff := math.Abs(br8-cr8) > thresholdValue ||
				math.Abs(bg8-cg8) > thresholdValue ||
				math.Abs(bb8-cb8) > thresholdValue ||
				math.Abs(ba8-ca8) > thresholdValue

			if isDiff {
				diffPixels++
				// Highlight in magenta for diff overlay
				diffImage.Set(x, y, color.RGBA{R: 255, G: 0, B: 255, A: 255})
			} else {
				// Dim the unchanged pixel (30% opacity of the current image)
				diffImage.Set(x, y, color.RGBA{
					R: uint8(cr8 * 0.3),
					G: uint8(cg8 * 0.3),
					B: uint8(cb8 * 0.3),
					A: uint8(math.Max(ca8*0.3, 50)),
				})
			}
		}
	}

	diffPercent := float64(diffPixels) / float64(totalPixels) * 100.0

	status := StatusUnchanged
	if diffPixels > 0 {
		status = StatusChanged
	}

	return &Result{
		Name:         filepath.Base(currentPath),
		Status:       status,
		DiffPercent:  diffPercent,
		DiffPixels:   diffPixels,
		TotalPixels:  totalPixels,
		BaselinePath: baselinePath,
		CurrentPath:  currentPath,
		DiffImage:    diffImage,
	}, nil
}

// CompareDirectories compares all PNG files in two directories.
// Files are matched by name. Files only in baseline are "removed",
// files only in current are "added", and matching files are compared.
func CompareDirectories(baselineDir, currentDir string, threshold float64) ([]Result, error) {
	baselineFiles, err := listPNGs(baselineDir)
	if err != nil {
		return nil, fmt.Errorf("failed to list baseline directory: %w", err)
	}

	currentFiles, err := listPNGs(currentDir)
	if err != nil {
		return nil, fmt.Errorf("failed to list current directory: %w", err)
	}

	// Build maps for lookup
	baselineMap := make(map[string]string, len(baselineFiles))
	for _, f := range baselineFiles {
		baselineMap[filepath.Base(f)] = f
	}

	currentMap := make(map[string]string, len(currentFiles))
	for _, f := range currentFiles {
		currentMap[filepath.Base(f)] = f
	}

	// Collect all unique names
	allNames := make(map[string]struct{})
	for name := range baselineMap {
		allNames[name] = struct{}{}
	}
	for name := range currentMap {
		allNames[name] = struct{}{}
	}

	var results []Result

	for name := range allNames {
		baselinePath, inBaseline := baselineMap[name]
		currentPath, inCurrent := currentMap[name]

		switch {
		case inBaseline && inCurrent:
			result, err := Compare(baselinePath, currentPath, threshold)
			if err != nil {
				return nil, fmt.Errorf("failed to compare %s: %w", name, err)
			}
			results = append(results, *result)

		case inBaseline && !inCurrent:
			results = append(results, Result{
				Name:         name,
				Status:       StatusRemoved,
				BaselinePath: baselinePath,
			})

		case !inBaseline && inCurrent:
			results = append(results, Result{
				Name:        name,
				Status:      StatusAdded,
				CurrentPath: currentPath,
			})
		}
	}

	// Sort: changed first (by diff % descending), then added, removed, unchanged
	sort.Slice(results, func(i, j int) bool {
		if results[i].Status != results[j].Status {
			return statusOrder(results[i].Status) < statusOrder(results[j].Status)
		}
		if results[i].Status == StatusChanged {
			return results[i].DiffPercent > results[j].DiffPercent
		}
		return results[i].Name < results[j].Name
	})

	return results, nil
}

// SaveDiffImage writes a diff overlay image to the specified path as PNG.
func SaveDiffImage(img image.Image, path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("failed to create directory: %w", err)
	}

	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("failed to create file: %w", err)
	}
	defer func() { _ = f.Close() }()

	if err := png.Encode(f, img); err != nil {
		return fmt.Errorf("failed to encode PNG: %w", err)
	}

	return nil
}

// decodePNG reads and decodes a PNG file.
func decodePNG(path string) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer func() { _ = f.Close() }()

	img, err := png.Decode(f)
	if err != nil {
		return nil, err
	}

	return img, nil
}

// listPNGs returns all .png files in a directory (non-recursive).
func listPNGs(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	var pngs []string
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		if strings.HasSuffix(strings.ToLower(entry.Name()), ".png") {
			pngs = append(pngs, filepath.Join(dir, entry.Name()))
		}
	}

	return pngs, nil
}

// statusOrder returns a sort priority for each status.
func statusOrder(s Status) int {
	switch s {
	case StatusChanged:
		return 0
	case StatusAdded:
		return 1
	case StatusRemoved:
		return 2
	case StatusUnchanged:
		return 3
	default:
		return 4
	}
}
