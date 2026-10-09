// Package agents provides helpers for working with Onyx agents (personas).
package agents

import (
	"fmt"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// ResolveByName finds an agent by exact name (case-insensitive), or by unique
// substring match. Returns an error when no agent matches or when multiple
// agents match.
func ResolveByName(agents []models.AgentSummary, name string) (models.AgentSummary, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return models.AgentSummary{}, fmt.Errorf("agent name cannot be empty")
	}

	exact := ExactNameMatches(agents, name)
	switch len(exact) {
	case 1:
		return exact[0], nil
	case 0:
		// fall through to substring match
	default:
		return models.AgentSummary{}, ambiguousError(name, exact)
	}

	low := strings.ToLower(name)

	var subs []models.AgentSummary
	for _, a := range agents {
		if strings.Contains(strings.ToLower(strings.TrimSpace(a.Name)), low) {
			subs = append(subs, a)
		}
	}
	switch len(subs) {
	case 1:
		return subs[0], nil
	case 0:
		return models.AgentSummary{}, fmt.Errorf(
			"no agent matches %q; run onyx-cli agents to list available agents",
			name,
		)
	default:
		return models.AgentSummary{}, ambiguousError(name, subs)
	}
}

// ExactNameMatches returns agents whose trimmed name equals name (case-insensitive).
func ExactNameMatches(agents []models.AgentSummary, name string) []models.AgentSummary {
	name = strings.TrimSpace(name)
	if name == "" {
		return nil
	}
	low := strings.ToLower(name)
	var exact []models.AgentSummary
	for _, a := range agents {
		if strings.ToLower(strings.TrimSpace(a.Name)) == low {
			exact = append(exact, a)
		}
	}
	return exact
}

func ambiguousError(name string, matches []models.AgentSummary) error {
	const maxShown = 8
	parts := make([]string, 0, min(len(matches), maxShown))
	for i, a := range matches {
		if i >= maxShown {
			break
		}
		parts = append(parts, fmt.Sprintf("%q (id %d)", a.Name, a.ID))
	}
	suffix := strings.Join(parts, ", ")
	if len(matches) > maxShown {
		suffix += fmt.Sprintf(", … (%d more)", len(matches)-maxShown)
	}
	return fmt.Errorf("%q is ambiguous: %s; use an exact name or --agent-id", name, suffix)
}
