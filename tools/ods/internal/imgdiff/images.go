package imgdiff

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// ImagesDirName is the sub-directory of the report directory that holds the
// per-screenshot PNGs written by WriteImages.
const ImagesDirName = "images"

// WriteImages writes the baseline, current, and diff PNGs for every screenshot
// that differs from the baseline into dir/images/{baseline,current,diff}/.
//
// The HTML report inlines its images as data URIs, which makes it
// self-contained but useless to anything that needs real files. CI uploads
// these copies so the PR comment can attach them.
//
// Unchanged screenshots are skipped. A changed screenshot produces all three
// images; an added one has no baseline and a removed one has no current, so
// only the images that exist are written.
func WriteImages(results []Result, dir string) error {
	imagesDir := filepath.Join(dir, ImagesDirName)

	for _, r := range results {
		if r.Status == StatusUnchanged {
			continue
		}

		name := filepath.Base(r.Name)

		if r.BaselinePath != "" {
			dest := filepath.Join(imagesDir, "baseline", name)
			if err := copyFile(r.BaselinePath, dest); err != nil {
				return fmt.Errorf("failed to write baseline image %s: %w", r.Name, err)
			}
		}

		if r.CurrentPath != "" {
			dest := filepath.Join(imagesDir, "current", name)
			if err := copyFile(r.CurrentPath, dest); err != nil {
				return fmt.Errorf("failed to write current image %s: %w", r.Name, err)
			}
		}

		if r.DiffImage != nil {
			dest := filepath.Join(imagesDir, "diff", name)
			if err := SaveDiffImage(r.DiffImage, dest); err != nil {
				return fmt.Errorf("failed to write diff image %s: %w", r.Name, err)
			}
		}
	}

	return nil
}

// copyFile copies src to dest, creating parent directories as needed.
func copyFile(src, dest string) error {
	if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
		return fmt.Errorf("failed to create directory: %w", err)
	}

	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()

	out, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer func() { _ = out.Close() }()

	if _, err := io.Copy(out, in); err != nil {
		return err
	}

	return out.Close()
}
