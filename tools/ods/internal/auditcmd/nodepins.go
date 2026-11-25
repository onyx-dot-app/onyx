package auditcmd

import (
	"encoding/json"
	"fmt"
	"slices"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/basedigest"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

type nodeImagePin struct {
	Image     string   `json:"image"`
	Consumers []string `json:"consumers"`
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

func newNodeImagePinsCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "node-image-pins",
		Short: "List pinned Node images and their consumers as JSON",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			root, err := paths.GitRoot()
			if err != nil {
				return err
			}
			files, err := basedigest.TrackedFiles(root)
			if err != nil {
				return err
			}
			refs, err := basedigest.FindRefs(root, files)
			if err != nil {
				return err
			}
			pins := nodeImagePins(refs)
			if len(pins) == 0 {
				return fmt.Errorf("no pinned Node images found")
			}
			return json.NewEncoder(cmd.OutOrStdout()).Encode(pins)
		},
	}
}

func newNodeRuntimesCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "node-runtimes",
		Short: "Read observed Node image versions as JSON and report Linux advisories for nightly alert sync",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var runtimes []audit.NodeRuntime
			if err := json.NewDecoder(cmd.InOrStdin()).Decode(&runtimes); err != nil {
				return err
			}
			result, err := audit.CheckNodeRuntimes(runtimes)
			if err != nil {
				return err
			}
			return json.NewEncoder(cmd.OutOrStdout()).Encode(result)
		},
	}
}
