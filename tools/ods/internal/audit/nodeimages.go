package audit

import (
	"fmt"
	"slices"
	"strings"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/basedigest"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

type nodeImagePin struct {
	Image     string
	Consumers []string
}

func nodeImagePins(refs []basedigest.Ref) []nodeImagePin {
	var pins []nodeImagePin
	byDigest := make(map[string]int)
	for _, ref := range refs {
		// kindest/node is a Kubernetes node image.
		switch ref.Name {
		case "node", "library/node", "docker.io/library/node", "dhi.io/node":
		default:
			continue
		}
		i, found := byDigest[ref.Digest]
		if !found {
			i = len(pins)
			byDigest[ref.Digest] = i
			pins = append(pins, nodeImagePin{Image: ref.Query() + "@" + ref.Digest})
		}
		pin := &pins[i]
		consumer := ref.Path
		if !slices.Contains(pin.Consumers, consumer) {
			pin.Consumers = append(pin.Consumers, consumer)
		}
	}
	return pins
}

// ScanNodeImages collects unsuppressed scan inputs for nightly alert sync.
// The web job already scans the hardened runtime's OS packages.
func ScanNodeImages(webImage string) (*Result, error) {
	root, err := paths.GitRoot()
	if err != nil {
		return nil, err
	}
	files, err := basedigest.TrackedFiles(root)
	if err != nil {
		return nil, err
	}
	refs, err := basedigest.FindRefs(root, files)
	if err != nil {
		return nil, err
	}
	pins := nodeImagePins(refs)
	if len(pins) == 0 {
		return nil, fmt.Errorf("no pinned Node images found")
	}
	_, webDigest, ok := strings.Cut(webImage, "@")
	if !ok || webDigest == "" {
		return nil, fmt.Errorf("web runtime must be pinned by digest: %q", webImage)
	}
	result := &Result{}
	for _, pin := range pins {
		if strings.HasSuffix(pin.Image, "@"+webDigest) {
			continue
		}
		findings, err := scanOSImage(pin.Image, true)
		if err != nil {
			return nil, fmt.Errorf("scan %s: %w", pin.Image, err)
		}
		for i := range findings {
			findings[i].Image = pin.Image
		}
		// Deduplicate within the image so a shared finding keeps every affected image.
		image := filterFindings(findings, "", SeverityCritical)
		result.Findings = append(result.Findings, image.Findings...)
		result.Blocking = append(result.Blocking, image.Blocking...)
	}
	return result, nil
}
