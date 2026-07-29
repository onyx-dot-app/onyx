package install

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
)

// managedFiles returns the files for the selected mode: the base set plus the
// overlays that apply. Prod swaps in its own set — the standalone prod
// compose file and the prod env/nginx templates — and deliberately leaves
// out the README: prod installs are typically adopted in place (sometimes
// inside a checked-out source tree), and dropping a README into someone's
// root is not adoption.
func managedFiles(prod, lite, craft bool) []deployfiles.File {
	var files []deployfiles.File
	if prod {
		files = []deployfiles.File{
			deployfiles.ProdCompose,
			deployfiles.EnvProdTemplate,
			deployfiles.EnvNginxTemplate,
			deployfiles.NginxAppConfProd,
			deployfiles.NginxRunScript,
		}
	} else {
		files = []deployfiles.File{
			deployfiles.Compose,
			deployfiles.EnvTemplate,
			deployfiles.Readme,
			deployfiles.NginxAppConf,
			deployfiles.NginxRunScript,
		}
	}
	if lite {
		files = append(files, deployfiles.LiteOverlay)
	}
	if craft {
		files = append(files, deployfiles.CraftOverlay)
	}
	return files
}

// fileFetcher sources managed-file content for a ref, falling back to the
// embedded copies. Once the network itself fails it stops trying (each fetch
// retries with delays; offline, every remaining file would pay that).
type fileFetcher struct {
	in       *installer
	disabled bool
}

// content returns the file's bytes for ref plus a short provenance label.
// ref == "" means "use embedded" (no fetch attempted).
func (ff *fileFetcher) content(ctx context.Context, ref string, f deployfiles.File) ([]byte, string, error) {
	if ref != "" && !ff.disabled {
		data, err := ff.in.deps.Release.FetchFile(ctx, ref, f.RepoPath)
		if err == nil {
			return data, ref, nil
		}
		// A file missing from a reachable ref (an overlay added after that
		// release, say) says nothing about the rest: falling back for the
		// whole set here would quietly mix one version's compose file with
		// another's overlays and nginx config.
		if errors.Is(err, release.ErrNotFound) {
			ff.in.warnf("%s doesn't exist at %s — using the copy bundled with this CLI, which may not match that version", f.RepoPath, ref)
		} else {
			ff.disabled = true
			ff.in.warnf("Could not fetch %s at %s (%v) — using the files bundled with this CLI", f.RepoPath, ref, err)
		}
	}
	data, err := f.Content()
	if err != nil {
		return nil, "", fmt.Errorf("embedded copy of %s is unreadable: %w", f.RepoPath, err)
	}
	return data, "embedded", nil
}

// materializeFiles brings every managed file on disk to the wanted state for
// ref, respecting --local (trust what's on disk, only fill gaps from the
// embedded copies) and user edits (detected via the manifest; edited files
// are backed up and only overwritten with consent or --force). The manifest
// is updated in place; the caller saves it.
func (in *installer) materializeFiles(
	ctx context.Context,
	ref string,
	files []deployfiles.File,
	manifest *state.Manifest,
	fetcher *fileFetcher,
) error {
	root := in.root.Dir
	for _, f := range files {
		dest := filepath.Join(root, filepath.FromSlash(f.DestRel))
		if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
			return fmt.Errorf("failed to create directory for %s: %w", f.DestRel, err)
		}
		onDisk, err := os.ReadFile(dest)
		exists := err == nil
		if err != nil && !os.IsNotExist(err) {
			return fmt.Errorf("failed to read %s: %w", f.DestRel, err)
		}

		if in.localFiles() {
			if exists {
				in.successf("Using existing %s", f.DestRel)
				if err := manifest.RecordFile(root, f.DestRel, onDisk); err != nil {
					return err
				}
				continue
			}
			// install.sh --local errors on missing files; the embedded
			// copies let the CLI fill the gap instead.
			in.infof("%s missing — writing the copy bundled with this CLI", f.DestRel)
		}

		var want []byte
		source := "embedded"
		if !in.localFiles() {
			want, source, err = fetcher.content(ctx, ref, f)
		} else {
			want, err = f.Content()
		}
		if err != nil {
			return err
		}

		if exists && string(onDisk) == string(want) {
			if err := manifest.RecordFile(root, f.DestRel, want); err != nil {
				return err
			}
			continue
		}

		if exists {
			edited, err := manifest.UserEdited(root, f.DestRel)
			if err != nil {
				return err
			}
			if edited {
				overwrite, err := in.confirmOverwriteEdited(f.DestRel)
				if err != nil {
					return err
				}
				if !overwrite {
					in.warnf("Keeping your %s — it may not match the deployed version", f.DestRel)
					continue
				}
				if err := in.backupFile(dest, f.DestRel, manifest); err != nil {
					return err
				}
			}
		}

		if err := os.WriteFile(dest, want, f.Mode); err != nil {
			return fmt.Errorf("failed to write %s: %w", f.DestRel, err)
		}
		// WriteFile only applies the mode on creation; keep the exec bit on
		// updates too.
		if err := os.Chmod(dest, f.Mode); err != nil {
			return fmt.Errorf("failed to chmod %s: %w", f.DestRel, err)
		}
		if err := manifest.RecordFile(root, f.DestRel, want); err != nil {
			return err
		}
		if exists {
			in.successf("Updated %s (%s)", f.DestRel, source)
		} else {
			in.successf("%s ready (%s)", f.DestRel, source)
		}
	}
	return nil
}

// removeOverlayIfPresent deletes a deselected overlay (e.g. switching from
// lite to standard) and drops it from the manifest.
func (in *installer) removeOverlayIfPresent(f deployfiles.File, manifest *state.Manifest, reason string) error {
	dest := filepath.Join(in.root.Dir, filepath.FromSlash(f.DestRel))
	if _, err := os.Stat(dest); os.IsNotExist(err) {
		return nil
	}
	if err := os.Remove(dest); err != nil {
		return fmt.Errorf("failed to remove %s: %w", f.DestRel, err)
	}
	if err := manifest.ForgetFile(in.root.Dir, f.DestRel); err != nil {
		return err
	}
	in.infof("Removed %s (%s)", f.DestRel, reason)
	return nil
}

// confirmOverwriteEdited gates replacing a file the CLI cannot vouch for:
// hand-edited since the last managed write, or present in a deployment that
// predates the manifest.
func (in *installer) confirmOverwriteEdited(destRel string) (bool, error) {
	if in.opts.Force {
		return true, nil
	}
	in.warnf("%s differs from what the CLI last wrote (hand-edited, or from an older installer).", destRel)
	if in.prompt.AssumeDefaults {
		in.warnf("Keeping it. Re-run with --force to overwrite (a backup is made).")
		return false, nil
	}
	return in.confirmYN(fmt.Sprintf("Overwrite %s? A backup will be kept.", destRel), false)
}

// backupFile snapshots dest before an overwrite, versioned so repeated
// upgrades don't clobber earlier backups.
func (in *installer) backupFile(dest, destRel string, manifest *state.Manifest) error {
	fromTag := "unmanaged"
	if manifest != nil && manifest.InstalledTag != "" {
		fromTag = manifest.InstalledTag
	}
	backup := fmt.Sprintf("%s.bak-%s-%d", dest, fromTag, time.Now().Unix())
	data, err := os.ReadFile(dest)
	if err != nil {
		return err
	}
	if err := os.WriteFile(backup, data, 0644); err != nil {
		return fmt.Errorf("failed to back up %s: %w", destRel, err)
	}
	in.infof("Backed up %s to %s", destRel, filepath.Base(backup))
	return nil
}
