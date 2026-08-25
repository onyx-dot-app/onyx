// Package basedigest refreshes the pinned base image digests across the Onyx
// repository.
//
// Every base image in the repo is pinned as `<name>:<tag>@sha256:<digest>`, and
// most FROM lines prefix the name with the ${BASE_IMAGE_REGISTRY} build arg so CI
// can route through the ECR pull-through cache. Dependabot's Docker parser rejects
// any FROM line that interpolates a variable, so it finds no dependencies in this
// repo and opens no pull requests. The Docker Hardened Image digests are worse off
// still: they live in a shell heredoc in .github/actions/dhi-base-images/action.yml,
// which no Dependabot ecosystem reads at all.
//
// This package replaces that missing coverage. It finds every pinned reference,
// asks the registry what the tag points at now, and rewrites the digests in place.
package basedigest

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/google/go-containerregistry/pkg/authn"
	"github.com/google/go-containerregistry/pkg/crane"
	"github.com/google/go-containerregistry/pkg/v1/remote/transport"
)

// defaultRegistry is where a reference carrying the ${BASE_IMAGE_REGISTRY} build
// arg resolves. The arg always stands in for a registry host, and CI only ever
// points it at a pull-through cache of Docker Hub.
const defaultRegistry = "docker.io"

// imageRef matches a fully pinned image reference: an optional registry-arg
// prefix, then name, tag and digest. Requiring both a tag and a 64-hex digest
// keeps this off GitHub Actions `uses:` pins, which are 40-hex commit shas, and
// off prose that spells out the reference format.
var imageRef = regexp.MustCompile(
	`(\$\{BASE_IMAGE_REGISTRY\}/)?` +
		`([a-z0-9][a-z0-9._-]*(?:[/.][a-z0-9._-]+)*)` +
		`:([A-Za-z0-9_][A-Za-z0-9._-]*)` +
		`@(sha256:[0-9a-f]{64})`)

// Ref is one pinned image reference found in a tracked file.
type Ref struct {
	Path     string // repo-relative
	Line     int    // 1-indexed
	Start    int    // byte offset of the digest within the line
	End      int
	Name     string
	Tag      string
	Digest   string
	Prefixed bool // carried the ${BASE_IMAGE_REGISTRY} prefix
}

// Query is the reference to ask the registry about.
func (r Ref) Query() string {
	if r.Prefixed {
		return fmt.Sprintf("%s/%s:%s", defaultRegistry, r.Name, r.Tag)
	}
	return fmt.Sprintf("%s:%s", r.Name, r.Tag)
}

// Display is the reference as written, without the registry arg.
func (r Ref) Display() string {
	return fmt.Sprintf("%s:%s", r.Name, r.Tag)
}

// Family is the base this reference belongs to, used to group it into one pull
// request. It is the last path segment of the name, so a public base and its
// hardened counterpart share a family: library/python, dhi.io/python and a bare
// python all land in "python". Bumping them together keeps the default base and
// the DHI override CI substitutes for it from drifting apart.
func (r Ref) Family() string {
	if i := strings.LastIndex(r.Name, "/"); i >= 0 {
		return r.Name[i+1:]
	}
	return r.Name
}

// TrackedFiles returns the tracked files under root that may pin a base image
// digest: every Dockerfile, plus the workflow and composite-action YAML that
// carries an image reference of its own.
func TrackedFiles(root string) ([]string, error) {
	cmd := exec.Command("git", "ls-files", "-z")
	cmd.Dir = root
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("git ls-files: %w", err)
	}

	var paths []string
	for entry := range strings.SplitSeq(string(out), "\x00") {
		if entry == "" {
			continue
		}
		base := filepath.Base(entry)
		ext := filepath.Ext(entry)
		inCI := strings.HasPrefix(entry, ".github/workflows/") ||
			strings.HasPrefix(entry, ".github/actions/")
		if strings.HasPrefix(base, "Dockerfile") || (inCI && (ext == ".yml" || ext == ".yaml")) {
			paths = append(paths, entry)
		}
	}
	sort.Strings(paths)
	return paths, nil
}

// FindRefs collects every pinned reference in the given repo-relative paths.
func FindRefs(root string, paths []string) ([]Ref, error) {
	var refs []Ref
	for _, path := range paths {
		data, err := os.ReadFile(filepath.Join(root, path))
		if err != nil {
			return nil, fmt.Errorf("read %s: %w", path, err)
		}
		for i, line := range strings.Split(string(data), "\n") {
			for _, m := range imageRef.FindAllStringSubmatchIndex(line, -1) {
				refs = append(refs, Ref{
					Path:     path,
					Line:     i + 1,
					Start:    m[8],
					End:      m[9],
					Name:     line[m[4]:m[5]],
					Tag:      line[m[6]:m[7]],
					Digest:   line[m[8]:m[9]],
					Prefixed: m[2] != -1,
				})
			}
		}
	}
	return refs, nil
}

// Resolve returns the digest that query currently points at.
//
// For a multi-arch image this is the manifest-list digest, which is what the repo
// pins so a single reference serves both amd64 and arm64 builds. Credentials come
// from the ambient Docker keychain, so `docker login dhi.io` covers the private
// DHI catalog.
func Resolve(query string) (string, error) {
	const attempts = 3
	var lastErr error
	for attempt := range attempts {
		if attempt > 0 {
			// A run resolves enough tags to draw a Docker Hub rate limit, so back
			// off and retry rather than failing the whole refresh.
			time.Sleep(time.Duration(5*attempt) * time.Second)
		}
		digest, err := crane.Digest(query, crane.WithAuthFromKeychain(authn.DefaultKeychain))
		if err == nil {
			return digest, nil
		}
		lastErr = err
		if !retryable(err) {
			break
		}
	}
	return "", fmt.Errorf("could not resolve %s: %w", query, lastErr)
}

// retryable reports whether err is a transient registry failure worth another
// attempt. A rate limit clears on its own; an unknown manifest or a rejected
// credential never will, so those fail immediately.
func retryable(err error) bool {
	if terr, ok := errors.AsType[*transport.Error](err); ok {
		return terr.StatusCode == 429 || terr.StatusCode >= 500
	}
	// A transport-level failure (DNS, TLS, connection reset) carries no status.
	return true
}

// ResolveAll resolves every distinct tag in refs, reporting all failures together
// rather than stopping at the first. A skipped registry means a base image
// silently stays stale, which is the exact failure this package exists to prevent.
func ResolveAll(refs []Ref) (map[string]string, error) {
	queries := map[string]bool{}
	for _, ref := range refs {
		queries[ref.Query()] = true
	}
	ordered := make([]string, 0, len(queries))
	for query := range queries {
		ordered = append(ordered, query)
	}
	sort.Strings(ordered)

	resolved := map[string]string{}
	var failures []string
	for _, query := range ordered {
		digest, err := Resolve(query)
		if err != nil {
			failures = append(failures, err.Error())
			continue
		}
		resolved[query] = digest
	}
	if len(failures) > 0 {
		return nil, errors.New(strings.Join(failures, "\n"))
	}
	return resolved, nil
}

// Stale returns the references whose pinned digest no longer matches the registry.
func Stale(refs []Ref, resolved map[string]string) []Ref {
	var stale []Ref
	for _, ref := range refs {
		if ref.Digest != resolved[ref.Query()] {
			stale = append(stale, ref)
		}
	}
	return stale
}

// Families returns the sorted, deduplicated families covered by refs.
func Families(refs []Ref) []string {
	seen := map[string]bool{}
	for _, ref := range refs {
		seen[ref.Family()] = true
	}
	families := make([]string, 0, len(seen))
	for family := range seen {
		families = append(families, family)
	}
	sort.Strings(families)
	return families
}

// FilterFamily returns only the references belonging to family.
func FilterFamily(refs []Ref, family string) []Ref {
	var kept []Ref
	for _, ref := range refs {
		if ref.Family() == family {
			kept = append(kept, ref)
		}
	}
	return kept
}

// Rewrite applies the resolved digests to the files the given references live in.
func Rewrite(root string, refs []Ref, resolved map[string]string) error {
	byPath := map[string][]Ref{}
	for _, ref := range refs {
		byPath[ref.Path] = append(byPath[ref.Path], ref)
	}

	for path, pathRefs := range byPath {
		full := filepath.Join(root, path)
		data, err := os.ReadFile(full)
		if err != nil {
			return fmt.Errorf("read %s: %w", path, err)
		}
		lines := strings.Split(string(data), "\n")

		// Work back to front so an earlier replacement cannot shift a later span.
		sort.Slice(pathRefs, func(i, j int) bool {
			if pathRefs[i].Line != pathRefs[j].Line {
				return pathRefs[i].Line > pathRefs[j].Line
			}
			return pathRefs[i].Start > pathRefs[j].Start
		})
		for _, ref := range pathRefs {
			line := lines[ref.Line-1]
			lines[ref.Line-1] = line[:ref.Start] + resolved[ref.Query()] + line[ref.End:]
		}

		info, err := os.Stat(full)
		if err != nil {
			return fmt.Errorf("stat %s: %w", path, err)
		}
		if err := os.WriteFile(full, []byte(strings.Join(lines, "\n")), info.Mode()); err != nil {
			return fmt.Errorf("write %s: %w", path, err)
		}
	}
	return nil
}

// SummaryTable renders the stale references as a markdown table, for a run summary
// or a pull request body.
func SummaryTable(refs []Ref, resolved map[string]string) string {
	if len(refs) == 0 {
		return "All pinned digests are current.\n"
	}
	var b strings.Builder
	b.WriteString("| Image | Tag | New digest | File |\n| --- | --- | --- | --- |\n")
	for _, ref := range refs {
		short := strings.TrimPrefix(resolved[ref.Query()], "sha256:")
		if len(short) > 12 {
			short = short[:12]
		}
		fmt.Fprintf(&b, "| `%s` | `%s` | `%s` | `%s:%d` |\n",
			ref.Name, ref.Tag, short, ref.Path, ref.Line)
	}
	return b.String()
}
