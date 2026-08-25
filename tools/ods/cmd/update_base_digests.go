package cmd

import (
	"encoding/json"
	"fmt"
	"maps"
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/basedigest"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// NewUpdateBaseDigestsCommand creates the update-base-digests command.
func NewUpdateBaseDigestsCommand() *cobra.Command {
	var (
		write             bool
		summaryFile       string
		family            string
		listStaleFamilies bool
		cacheFile         string
	)

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
      --cache-file digests.json                            # rewrite one family`,
		Run: func(cmd *cobra.Command, args []string) {
			runUpdateBaseDigests(write, summaryFile, family, listStaleFamilies, cacheFile)
		},
	}

	cmd.Flags().BoolVar(&write, "write", false, "rewrite the files; without it the command only reports")
	cmd.Flags().StringVar(&summaryFile, "summary-file", "", "write a markdown summary of the changes to this path")
	cmd.Flags().StringVar(&family, "family", "", "only act on one base family, for example `python` or `node`")
	cmd.Flags().BoolVar(&listStaleFamilies, "list-stale-families", false, "print the families that have a stale digest, one per line, and exit")
	cmd.Flags().StringVar(&cacheFile, "cache-file", "", "read resolved digests from this path, or write them there if absent")

	return cmd
}

func runUpdateBaseDigests(write bool, summaryFile, family string, listStaleFamilies bool, cacheFile string) {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Could not find the repository root: %v", err)
	}

	files, err := basedigest.TrackedFiles(root)
	if err != nil {
		log.Fatalf("Could not list the tracked files: %v", err)
	}

	refs, err := basedigest.FindRefs(root, files)
	if err != nil {
		log.Fatalf("Could not read the tracked files: %v", err)
	}
	if len(refs) == 0 {
		log.Fatal("No pinned image references found.")
	}

	resolved, err := resolveWithCache(refs, cacheFile)
	if err != nil {
		log.Fatalf("Could not resolve every tag:\n%v", err)
	}

	stale := basedigest.Stale(refs, resolved)

	if listStaleFamilies {
		for _, name := range basedigest.Families(stale) {
			fmt.Println(name)
		}
		return
	}

	if family != "" {
		refs = basedigest.FilterFamily(refs, family)
		stale = basedigest.FilterFamily(stale, family)
		if len(refs) == 0 {
			log.Fatalf("No references in family %q.", family)
		}
	}

	for _, ref := range refs {
		state := "current"
		if ref.Digest != resolved[ref.Query()] {
			state = "update"
		}
		fmt.Printf("%7s  %-45s %s:%d\n", state, ref.Display(), ref.Path, ref.Line)
	}

	summary := basedigest.SummaryTable(stale, resolved)

	if len(stale) == 0 {
		fmt.Println("\nAll pinned digests are current.")
	} else if write {
		if err := basedigest.Rewrite(root, stale, resolved); err != nil {
			log.Fatalf("Could not rewrite the digests: %v", err)
		}
		fmt.Printf("\nUpdated %d reference(s).\n", len(stale))
	} else {
		fmt.Printf("\n%d reference(s) are stale. Re-run with --write to apply.\n", len(stale))
	}

	if summaryFile != "" {
		if err := os.WriteFile(summaryFile, []byte(summary), 0o644); err != nil {
			log.Fatalf("Could not write the summary: %v", err)
		}
	}
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
		data, err := os.ReadFile(cacheFile)
		switch {
		case err == nil:
			if err := json.Unmarshal(data, &cached); err != nil {
				return nil, fmt.Errorf("read cache %s: %w", cacheFile, err)
			}
		case !os.IsNotExist(err):
			return nil, fmt.Errorf("read cache %s: %w", cacheFile, err)
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
		data, err := json.MarshalIndent(resolved, "", "  ")
		if err != nil {
			return nil, fmt.Errorf("encode cache: %w", err)
		}
		if err := os.WriteFile(cacheFile, append(data, '\n'), 0o644); err != nil {
			return nil, fmt.Errorf("write cache %s: %w", cacheFile, err)
		}
	}
	return resolved, nil
}
