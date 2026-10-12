package cmd

import (
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/basedigest"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// UpdateBaseDigestsOptions holds options for the update-base-digests command.
type UpdateBaseDigestsOptions struct {
	Write             bool
	SummaryFile       string
	Family            string
	ListStaleFamilies bool
	CacheFile         string
	CachedOnly        bool
	PinsFile          string
}

// NewUpdateBaseDigestsCommand creates the update-base-digests command.
func NewUpdateBaseDigestsCommand() *cobra.Command {
	opts := &UpdateBaseDigestsOptions{}

	cmd := &cobra.Command{
		Use:   "update-base-digests",
		Short: "Refresh the pinned base image digests across the repository",
		Long: `Refresh the pinned base image digests across the repository.

Every base image here is pinned as <name>:<tag>@sha256:<digest>, and most FROM
lines prefix the name with the ${BASE_IMAGE_REGISTRY} build arg. Dependabot's
Docker parser rejects any FROM line that interpolates a variable, so it opens no
pull requests for this repo. This command covers those references instead: it
asks each registry what the tag points at now and rewrites the digest in place.

Credentials come from the ambient Docker keychain, so dhi.io references need a
` + "`docker login dhi.io`" + ` with an account that has DHI catalog access.

References group into families by the last segment of the image name, so a public
base and its DHI counterpart move together in one pull request.

Only digests are refreshed. A reference pinned to an immutable patch tag (for
example golang:1.26.5-alpine) never moves, so bumping it is still a manual edit.

Examples:
  ods update-base-digests                                  # report every reference
  ods update-base-digests --list-stale-families            # families needing a bump
  ods update-base-digests --write --family python \
      --cache-file digests.json                            # rewrite one family
  ods update-base-digests --pins-file digests.json         # dump this checkout's pins as a cache
  ods update-base-digests --write --family python \
      --cache-file digests.json --cached-only              # pin to another checkout's digests`,
		Run: func(cmd *cobra.Command, args []string) {
			output, err := runUpdateBaseDigests(opts)
			fmt.Print(output)
			if err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().BoolVar(&opts.Write, "write", false, "rewrite the files; without it the command only reports")
	cmd.Flags().StringVar(&opts.SummaryFile, "summary-file", "", "write a markdown summary of the changes to this path")
	cmd.Flags().StringVar(&opts.Family, "family", "", "only act on one base family, for example python or node")
	cmd.Flags().BoolVar(&opts.ListStaleFamilies, "list-stale-families", false, "print the families that have a stale digest, one per line, and exit")
	cmd.Flags().StringVar(&opts.CacheFile, "cache-file", "", "read resolved digests from this path, or write them there if absent")
	cmd.Flags().BoolVar(&opts.CachedOnly, "cached-only", false, "touch only the references --cache-file covers and ask no registry; the rest are kept as pinned")
	cmd.Flags().StringVar(&opts.PinsFile, "pins-file", "", "write the digests this checkout pins as a cache file and exit, so another checkout can be pinned to them with --cache-file --cached-only")

	return cmd
}

// runUpdateBaseDigests returns what Run prints, and an error whose text is the
// message Run logs before exiting.
func runUpdateBaseDigests(opts *UpdateBaseDigestsOptions) (string, error) {
	var out strings.Builder

	root, err := paths.GitRoot()
	if err != nil {
		return out.String(), fatalErrorf("Could not find the repository root: %v", err)
	}

	files, err := basedigest.TrackedFiles(root)
	if err != nil {
		return out.String(), fatalErrorf("Could not list the tracked files: %v", err)
	}

	refs, err := basedigest.FindRefs(root, files)
	if err != nil {
		return out.String(), fatalErrorf("Could not read the tracked files: %v", err)
	}
	if len(refs) == 0 {
		return out.String(), fatalErrorf("No pinned image references found.")
	}

	if opts.PinsFile != "" {
		if err := writePins(refs, opts.PinsFile); err != nil {
			return out.String(), fatalErrorf("Could not write the pins: %v", err)
		}
		fmt.Fprintf(&out, "Wrote %d pinned reference(s) to %s.\n", len(refs), opts.PinsFile)
		return out.String(), nil
	}

	// Filter before resolving, so one family's rewrite never asks a registry
	// about another family's tags.
	if opts.Family != "" {
		refs = basedigest.FilterFamily(refs, opts.Family)
		if len(refs) == 0 {
			return out.String(), fatalErrorf("No references in family %q.", opts.Family)
		}
	}

	var resolved map[string]string
	if opts.CachedOnly {
		if opts.CacheFile == "" {
			return out.String(), fatalErrorf("--cached-only needs --cache-file.")
		}
		resolved, err = readCache(opts.CacheFile)
		if err != nil {
			return out.String(), fatalErrorf("Could not read the cache: %v", err)
		}
	} else {
		resolved, err = resolveWithCache(refs, opts.CacheFile)
		if err != nil {
			return out.String(), fatalErrorf("Could not resolve every tag:\n%v", err)
		}
	}

	// A reference the cache leaves out is kept as pinned, so a tag the other
	// checkout dropped never changes and nothing gets a blank digest.
	var covered []basedigest.Ref
	for _, ref := range refs {
		if _, ok := resolved[ref.Query()]; ok {
			covered = append(covered, ref)
		}
	}
	stale := basedigest.Stale(covered, resolved)

	if opts.ListStaleFamilies {
		for _, name := range basedigest.Families(stale) {
			out.WriteString(name + "\n")
		}
		return out.String(), nil
	}

	for _, ref := range refs {
		state := "current"
		if digest, ok := resolved[ref.Query()]; !ok {
			state = "kept"
		} else if ref.Digest != digest {
			state = "update"
		}
		fmt.Fprintf(&out, "%7s  %-45s %s:%d\n", state, ref.Display(), ref.Path, ref.Line)
	}

	summary := basedigest.SummaryTable(stale, resolved)

	if len(stale) == 0 {
		out.WriteString("\nAll pinned digests are current.\n")
	} else if opts.Write {
		if err := basedigest.Rewrite(root, stale, resolved); err != nil {
			return out.String(), fatalErrorf("Could not rewrite the digests: %v", err)
		}
		fmt.Fprintf(&out, "\nUpdated %d reference(s).\n", len(stale))
	} else {
		fmt.Fprintf(&out, "\n%d reference(s) are stale. Re-run with --write to apply.\n", len(stale))
	}

	if opts.SummaryFile != "" {
		if err := os.WriteFile(opts.SummaryFile, []byte(summary), 0o644); err != nil {
			return out.String(), fatalErrorf("Could not write the summary: %v", err)
		}
	}
	return out.String(), nil
}

// writePins saves each ref's pinned digest in --cache-file form, so another
// checkout can be rewritten to this one's digests. Two pins of one tag that
// disagree have drifted, and the file would silently keep the last.
func writePins(refs []basedigest.Ref, pinsFile string) error {
	pins := map[string]string{}
	for _, ref := range refs {
		if other, ok := pins[ref.Query()]; ok && other != ref.Digest {
			return fmt.Errorf("%s is pinned to two digests, %s and %s", ref.Display(), other, ref.Digest)
		}
		pins[ref.Query()] = ref.Digest
	}
	return writeCache(pinsFile, pins)
}

// readCache loads a --cache-file, empty when the file does not exist yet.
func readCache(path string) (map[string]string, error) {
	cached := map[string]string{}
	data, err := os.ReadFile(path)
	switch {
	case err == nil:
		if err := json.Unmarshal(data, &cached); err != nil {
			return nil, fmt.Errorf("read cache %s: %w", path, err)
		}
	case !os.IsNotExist(err):
		return nil, fmt.Errorf("read cache %s: %w", path, err)
	}
	return cached, nil
}

// writeCache saves digests by query as the JSON --cache-file reads.
func writeCache(path string, digests map[string]string) error {
	data, err := json.MarshalIndent(digests, "", "  ")
	if err != nil {
		return fmt.Errorf("encode cache: %w", err)
	}
	if err := os.WriteFile(path, append(data, '\n'), 0o644); err != nil {
		return fmt.Errorf("write cache %s: %w", path, err)
	}
	return nil
}

// resolveWithCache resolves every distinct tag, reusing cacheFile when it exists.
//
// The cache lets a caller resolve once and then rewrite one family at a time
// against that single snapshot, so every branch of a run pins the same digests
// even if a tag moves while the run is in flight.
//
// A cache written before a new base image was added covers only part of the
// references. The entries it does have still hold the snapshot together, so the
// missing ones are resolved and merged in rather than discarding the file.
func resolveWithCache(refs []basedigest.Ref, cacheFile string) (map[string]string, error) {
	cached := map[string]string{}
	if cacheFile != "" {
		var err error
		if cached, err = readCache(cacheFile); err != nil {
			return nil, err
		}
	}

	missing := make([]basedigest.Ref, 0, len(refs))
	for _, ref := range refs {
		if _, ok := cached[ref.Query()]; !ok {
			missing = append(missing, ref)
		}
	}
	if len(missing) == 0 {
		return cached, nil
	}

	resolved, err := basedigest.ResolveAll(missing)
	if err != nil {
		return nil, err
	}
	maps.Copy(resolved, cached)

	if cacheFile != "" {
		if err := writeCache(cacheFile, resolved); err != nil {
			return nil, err
		}
	}
	return resolved, nil
}
