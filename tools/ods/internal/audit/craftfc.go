package audit

import (
	"cmp"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// SourceCraftFC marks findings for the Craft Firecracker guest kernel and
// Firecracker, which no package scanner can read.
const SourceCraftFC = "craft-fc-advisories"

// EcosystemCraftFC is the ecosystem of craft-fc findings. It has no ":", so
// CVE Alerts never reads a finding as an OS package of a base image.
const EcosystemCraftFC = "craft-fc"

const (
	// DefaultCraftFCDockerfile pins the guest kernel and Firecracker.
	DefaultCraftFCDockerfile = "deployment/craft-fc/Dockerfile.artifacts"
	// DefaultFirecrackerAdvisoriesURL lists the published Firecracker advisories.
	DefaultFirecrackerAdvisoriesURL = "https://api.github.com/repos/firecracker-microvm/firecracker/security-advisories?per_page=100"
	// DefaultALASFeedURL is the Amazon Linux 2023 advisory feed. The guest
	// kernel is an amazonlinux/linux tag (kernel6.18-... or microvm-kernel-...),
	// which shares its version with the AL2023 kernel package of the series.
	DefaultALASFeedURL = "https://alas.aws.amazon.com/AL2023/alas.rss"
)

// CraftFCOptions configures a craft-fc advisory audit.
type CraftFCOptions struct {
	// Dockerfile holds the KERNEL_TAG and FC_VERSION pins. Relative paths
	// resolve from the repository root.
	Dockerfile               string
	FirecrackerAdvisoriesURL string
	ALASFeedURL              string
	Format                   string
	FailOn                   Severity
	IgnoreURL                string
	Stdout                   io.Writer
	Stderr                   io.Writer
}

// CraftFCPins are the versions Dockerfile.artifacts builds.
type CraftFCPins struct {
	// KernelPackage is the AL2023 package of the kernel series, e.g. kernel6.18.
	KernelPackage string
	// KernelVersion is the kernel tag without its prefix, e.g.
	// 6.18.62-127.179.amzn2023.
	KernelVersion string
	// FirecrackerVersion has no "v" prefix, e.g. 1.17.0.
	FirecrackerVersion string
}

var (
	// kernel6.18-<v>, microvm-kernel6.18-<v> or microvm-kernel-<v>.
	kernelTagRe   = regexp.MustCompile(`^(microvm-kernel|kernel)(\d+\.\d+)?-((\d+)\.(\d+)\.\d+-[0-9.]+\.amzn2023)$`)
	fcVersionRe   = regexp.MustCompile(`^v?(\d+\.\d+\.\d+)$`)
	alasTitleRe   = regexp.MustCompile(`^(ALAS2023-\d+-\d+) \(([a-z]+)\): (.+)$`)
	cveRe         = regexp.MustCompile(`CVE-\d{4}-\d+`)
	rangeTokenRe  = regexp.MustCompile(`^(>=|<=|>|<|=)?\s*v?(\d+(?:\.\d+)*)$`)
	nextLinkRe    = regexp.MustCompile(`<([^>]+)>;\s*rel="next"`)
	httpUserAgent = "onyx-ods-audit"
)

// ReadCraftFCPins reads KERNEL_TAG and FC_VERSION from a Dockerfile.
func ReadCraftFCPins(path string) (CraftFCPins, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return CraftFCPins{}, err
	}
	args := map[string]string{}
	for _, line := range strings.Split(string(data), "\n") {
		if rest, ok := strings.CutPrefix(strings.TrimSpace(line), "ARG "); ok {
			if k, v, ok := strings.Cut(rest, "="); ok {
				if _, seen := args[k]; !seen {
					args[k] = strings.TrimSpace(v)
				}
			}
		}
	}
	m := kernelTagRe.FindStringSubmatch(args["KERNEL_TAG"])
	// The package tag always names its series; only microvm-kernel may omit it.
	if m == nil || (m[2] == "" && m[1] == "kernel") || (m[2] != "" && m[2] != m[4]+"."+m[5]) {
		return CraftFCPins{}, fmt.Errorf("%s: KERNEL_TAG %q is not a kernel<series>-<version>.amzn2023 or microvm-kernel-<version>.amzn2023 tag", path, args["KERNEL_TAG"])
	}
	fc := fcVersionRe.FindStringSubmatch(args["FC_VERSION"])
	if fc == nil {
		return CraftFCPins{}, fmt.Errorf("%s: FC_VERSION %q is not vX.Y.Z", path, args["FC_VERSION"])
	}
	return CraftFCPins{
		KernelPackage:      "kernel" + m[4] + "." + m[5],
		KernelVersion:      m[3],
		FirecrackerVersion: fc[1],
	}, nil
}

// RunCraftFC matches the pinned guest kernel against AL2023 advisories and
// the pinned Firecracker against its GitHub advisories. A feed that cannot be
// read fails the run, so a missed advisory never reads as fixed.
func RunCraftFC(opts CraftFCOptions) (*Result, error) {
	path := cmp.Or(opts.Dockerfile, DefaultCraftFCDockerfile)
	if !filepath.IsAbs(path) {
		root, err := paths.GitRoot()
		if err != nil {
			return nil, err
		}
		path = filepath.Join(root, path)
	}
	pins, err := ReadCraftFCPins(path)
	if err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: 60 * time.Second}
	kernel, err := kernelFindings(client, cmp.Or(opts.ALASFeedURL, DefaultALASFeedURL), pins)
	if err != nil {
		return nil, fmt.Errorf("guest kernel advisories: %w", err)
	}
	fc, err := firecrackerFindings(client, cmp.Or(opts.FirecrackerAdvisoriesURL, DefaultFirecrackerAdvisoriesURL), pins)
	if err != nil {
		return nil, fmt.Errorf("firecracker advisories: %w", err)
	}

	result := filterFindings(append(kernel, fc...), opts.IgnoreURL, opts.FailOn)
	result.ScannedPackages = []ScannedPackage{
		{Ecosystem: EcosystemCraftFC, Package: pins.KernelPackage},
		{Ecosystem: EcosystemCraftFC, Package: "firecracker"},
	}
	if err := renderReport(opts.Stdout, opts.Stderr, opts.Format, result); err != nil {
		return nil, err
	}
	return result, nil
}

func httpGet(client *http.Client, url string, headers map[string]string) ([]byte, http.Header, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("User-Agent", httpUserAgent)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return nil, nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, nil, fmt.Errorf("GET %s: HTTP %d", url, resp.StatusCode)
	}
	return body, resp.Header, nil
}

type alasFeed struct {
	Items []struct {
		Title       string `xml:"title"`
		Description string `xml:"description"`
		Link        string `xml:"link"`
	} `xml:"channel>item"`
}

// kernelFindings reports each AL2023 advisory for the kernel package whose
// fixed version is newer than the pin.
func kernelFindings(client *http.Client, feedURL string, pins CraftFCPins) ([]Finding, error) {
	body, _, err := httpGet(client, feedURL, nil)
	if err != nil {
		return nil, err
	}
	var feed alasFeed
	if err := xml.Unmarshal(body, &feed); err != nil {
		return nil, fmt.Errorf("parse %s: %w", feedURL, err)
	}
	if len(feed.Items) == 0 {
		return nil, fmt.Errorf("%s has no advisories", feedURL)
	}
	fixedRe := regexp.MustCompile(regexp.QuoteMeta(pins.KernelPackage) + `-(\d+\.\d+\.\d+-[0-9.]+\.amzn2023)\.x86_64`)
	var findings []Finding
	for _, item := range feed.Items {
		m := alasTitleRe.FindStringSubmatch(strings.TrimSpace(item.Title))
		if m == nil || !slices.Contains(strings.Split(m[3], ", "), pins.KernelPackage) {
			continue
		}
		page, _, err := httpGet(client, strings.TrimSpace(item.Link), nil)
		if err != nil {
			return nil, err
		}
		fixed := fixedRe.FindStringSubmatch(string(page))
		if fixed == nil {
			return nil, fmt.Errorf("%s names no x86_64 %s package", m[1], pins.KernelPackage)
		}
		if compareNumeric(fixed[1], pins.KernelVersion) <= 0 {
			continue
		}
		// The CVEs go in the title, not in Aliases: an advisory bundles
		// independent CVEs, and an allowlist entry for one alias would
		// suppress them all.
		findings = append(findings, Finding{
			ID:        m[1],
			Ecosystem: EcosystemCraftFC,
			Package:   pins.KernelPackage,
			Version:   pins.KernelVersion,
			Severity:  alasSeverity(m[2]),
			Title: fmt.Sprintf("fixed in %s %s: %s", pins.KernelPackage, fixed[1],
				strings.Join(cveRe.FindAllString(item.Description, -1), ", ")),
			URL:      strings.TrimSpace(item.Link),
			Source:   SourceCraftFC,
			FixedIn:  fixed[1],
			Manifest: DefaultCraftFCDockerfile,
		})
	}
	return findings, nil
}

// alasSeverity maps an Amazon Linux severity to a Severity.
func alasSeverity(s string) Severity {
	switch s {
	case "critical":
		return SeverityCritical
	case "important":
		return SeverityHigh
	case "medium":
		return SeverityModerate
	case "low":
		return SeverityLow
	default:
		return SeverityUnknown
	}
}

type ghAdvisory struct {
	GHSAID          string `json:"ghsa_id"`
	CVEID           string `json:"cve_id"`
	HTMLURL         string `json:"html_url"`
	Summary         string `json:"summary"`
	Severity        string `json:"severity"`
	Vulnerabilities []struct {
		Package struct {
			Name string `json:"name"`
		} `json:"package"`
		VulnerableVersionRange string `json:"vulnerable_version_range"`
		PatchedVersions        string `json:"patched_versions"`
	} `json:"vulnerabilities"`
}

// firecrackerFindings reports each Firecracker repository advisory whose
// vulnerable range holds the pinned version.
func firecrackerFindings(client *http.Client, url string, pins CraftFCPins) ([]Finding, error) {
	headers := map[string]string{"Accept": "application/vnd.github+json"}
	if token := firstNonEmpty(os.Getenv("GH_TOKEN"), os.Getenv("GITHUB_TOKEN")); token != "" {
		headers["Authorization"] = "Bearer " + token
	}
	var advisories []ghAdvisory
	for url != "" {
		body, header, err := httpGet(client, url, headers)
		if err != nil {
			return nil, err
		}
		var page []ghAdvisory
		if err := json.Unmarshal(body, &page); err != nil {
			return nil, fmt.Errorf("parse %s: %w", url, err)
		}
		advisories = append(advisories, page...)
		url = ""
		if m := nextLinkRe.FindStringSubmatch(header.Get("Link")); m != nil {
			url = m[1]
		}
	}
	var findings []Finding
	for _, a := range advisories {
		for _, v := range a.Vulnerabilities {
			if v.Package.Name != "" && !strings.EqualFold(v.Package.Name, "firecracker") {
				continue
			}
			if !versionInRange(pins.FirecrackerVersion, v.VulnerableVersionRange) {
				continue
			}
			var aliases []string
			if a.CVEID != "" {
				aliases = []string{a.CVEID}
			}
			findings = append(findings, Finding{
				ID:        a.GHSAID,
				Aliases:   aliases,
				Ecosystem: EcosystemCraftFC,
				Package:   "firecracker",
				Version:   pins.FirecrackerVersion,
				Severity:  ParseSeverity(a.Severity),
				Title:     a.Summary,
				URL:       a.HTMLURL,
				Source:    SourceCraftFC,
				FixedIn:   strings.TrimSpace(v.PatchedVersions),
				Manifest:  DefaultCraftFCDockerfile,
			})
			break
		}
	}
	return findings, nil
}

// versionInRange reports whether version is in a GitHub repository advisory
// range. These ranges are free text: comma-separated bounds, where a lower
// bound and the next upper bound form one interval and a bare version is an
// exact match, e.g. ">=1.13.0, <= 1.14.3, 1.15.0". A range it cannot read
// counts as a match, so the finding is reported for a person to check.
func versionInRange(version, rng string) bool {
	rng = strings.TrimSpace(rng)
	if rng == "" {
		return true
	}
	var lower string
	var lowerIncl, haveLower bool
	aboveLower := func() bool {
		c := compareNumeric(version, lower)
		return c > 0 || lowerIncl && c == 0
	}
	for _, raw := range strings.Split(rng, ",") {
		m := rangeTokenRe.FindStringSubmatch(strings.TrimSpace(raw))
		if m == nil {
			return true
		}
		op, v := m[1], m[2]
		switch op {
		case ">=", ">":
			// A lower bound with no upper bound before it matches everything above it.
			if haveLower && aboveLower() {
				return true
			}
			lower, lowerIncl, haveLower = v, op == ">=", true
		case "<=", "<":
			c := compareNumeric(version, v)
			if (c < 0 || op == "<=" && c == 0) && (!haveLower || aboveLower()) {
				return true
			}
			haveLower = false
		default:
			if compareNumeric(version, v) == 0 {
				return true
			}
		}
	}
	return haveLower && aboveLower()
}

// compareNumeric compares the numeric fields of two versions, split on "."
// and "-". A non-numeric field ends the comparison, so 6.18.25-57.115.amzn2023
// compares as 6.18.25-57.115.
func compareNumeric(a, b string) int {
	fa, fb := numericFields(a), numericFields(b)
	for i := 0; i < len(fa) || i < len(fb); i++ {
		var x, y int
		if i < len(fa) {
			x = fa[i]
		}
		if i < len(fb) {
			y = fb[i]
		}
		if x != y {
			if x < y {
				return -1
			}
			return 1
		}
	}
	return 0
}

func numericFields(v string) []int {
	var out []int
	for _, f := range strings.FieldsFunc(strings.TrimPrefix(v, "v"), func(r rune) bool { return r == '.' || r == '-' }) {
		n, err := strconv.Atoi(f)
		if err != nil {
			break
		}
		out = append(out, n)
	}
	return out
}
