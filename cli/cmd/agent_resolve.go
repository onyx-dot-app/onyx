package cmd

import (
	"context"

	"github.com/onyx-dot-app/onyx/cli/internal/agents"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

type agentLister interface {
	ListAgents(ctx context.Context) ([]models.AgentSummary, error)
}

// resolveAgentSelection maps CLI agent flags to the agent ID used for API calls.
// explicit is true when the caller passed --agent-id or --agent-name.
func resolveAgentSelection(
	ctx context.Context,
	client agentLister,
	agentID int,
	agentIDSet bool,
	agentName string,
	agentNameSet bool,
	defaultAgentID int,
) (resolvedID int, explicit bool, err error) {
	if agentIDSet && agentNameSet {
		return 0, false, exitcodes.New(exitcodes.BadRequest, "--agent-id and --agent-name are mutually exclusive")
	}
	if agentIDSet {
		return agentID, true, nil
	}
	if agentNameSet {
		list, err := client.ListAgents(ctx)
		if err != nil {
			return 0, false, apiErrorToExit(err, "listing agents")
		}
		agent, err := agents.ResolveByName(list, agentName)
		if err != nil {
			return 0, false, exitcodes.New(exitcodes.BadRequest, err.Error())
		}
		return agent.ID, true, nil
	}
	return defaultAgentID, false, nil
}
