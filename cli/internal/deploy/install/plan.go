package install

import (
	"runtime"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/release"
)

// printPlan renders --dry-run: what an install would do, with no side
// effects (mirrors install.sh's dry-run summary).
func (in *installer) printPlan(defaultTag string) {
	in.infof("Dry run mode — showing what would happen:")
	in.plainf("  • Install root: %s (%s)", in.root.Dir, in.root.Source)
	in.plainf("  • Lite mode: %t", in.lite)
	if in.craft {
		in.plainf("  • Include Craft: true")
	}
	in.plainf("  • OS: %s/%s (WSL: %t)", runtime.GOOS, runtime.GOARCH, dockercmd.IsWSL())
	switch {
	case in.opts.Offline:
		in.plainf("  • Default image tag: %s (from the images on this host)", defaultTag)
		in.plainf("  • Config files: existing files on disk, embedded copies for gaps (--offline)")
	case in.opts.Local:
		in.plainf("  • Config files: existing files on disk, embedded copies for gaps (--local)")
	default:
		in.plainf("  • Default image tag: %s (config ref: %s)", defaultTag, release.ConfigRef(defaultTag))
	}
	in.plainf("")
	in.successf("Dry run complete (no changes made)")
}
