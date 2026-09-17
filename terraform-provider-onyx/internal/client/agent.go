package client

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
)

// Onyx calls this resource an "agent", but only the list and display-priority
// routes are served under /admin/agents. Create, read, update, delete and
// listed still live under /persona, and the JSON keeps the older spelling in
// "personas" and "builtin_persona". Do not rewrite those paths or tags to match
// the Go names: the /admin/agents prefix has no equivalent for them, so the
// calls would 404 against every released Onyx.

// StarterMessage is one suggested opening prompt shown on an agent's card.
type StarterMessage struct {
	Name    string `json:"name"`
	Message string `json:"message"`
}

// AgentWrite mirrors PersonaUpsertRequest, which both create and update take.
//
// Several fields are nullable server-side, where null means "leave unchanged"
// rather than "clear". The provider manages the whole agent, so it sends every
// value it owns on every write and the tri-state never comes into play.
//
// HierarchyNodeIDs and DocumentIDs are the exception: Terraform does not manage
// them, but they default to an empty list when omitted, which would clear
// attachments made in the admin panel. Update reads the stored values and
// sends them back.
type AgentWrite struct {
	Name                        string           `json:"name"`
	Description                 string           `json:"description"`
	DocumentSetIDs              []int64          `json:"document_set_ids"`
	ToolIDs                     []int64          `json:"tool_ids"`
	SystemPrompt                string           `json:"system_prompt"`
	TaskPrompt                  string           `json:"task_prompt"`
	DatetimeAware               bool             `json:"datetime_aware"`
	ReplaceBaseSystemPrompt     bool             `json:"replace_base_system_prompt"`
	IsPublic                    *bool            `json:"is_public"`
	IsFeatured                  *bool            `json:"is_featured"`
	IconName                    *string          `json:"icon_name"`
	DisplayPriority             *int64           `json:"display_priority"`
	StarterMessages             []StarterMessage `json:"starter_messages"`
	LabelIDs                    []int64          `json:"label_ids"`
	DefaultModelConfigurationID *int64           `json:"default_model_configuration_id"`
	SearchStartDate             *string          `json:"search_start_date"`
	Users                       []string         `json:"users"`
	Groups                      []int64          `json:"groups"`
	HierarchyNodeIDs            []int64          `json:"hierarchy_node_ids"`
	DocumentIDs                 []string         `json:"document_ids"`
}

type agentToolRef struct {
	ID int64 `json:"id"`
}

type agentDocumentSetRef struct {
	ID int64 `json:"id"`
}

type agentLabelRef struct {
	ID int64 `json:"id"`
}

type agentUserRef struct {
	ID string `json:"id"`
}

type agentHierarchyNodeRef struct {
	ID int64 `json:"id"`
}

type agentAttachedDocumentRef struct {
	ID string `json:"id"`
}

// Agent mirrors PersonaSnapshot.
//
// The snapshot carries no search_start_date, so that field cannot be read back.
type Agent struct {
	ID                          int64                      `json:"id"`
	Name                        string                     `json:"name"`
	Description                 string                     `json:"description"`
	IsPublic                    bool                       `json:"is_public"`
	IsListed                    bool                       `json:"is_listed"`
	IsFeatured                  bool                       `json:"is_featured"`
	BuiltinAgent                bool                       `json:"builtin_persona"`
	IconName                    *string                    `json:"icon_name"`
	DisplayPriority             *int64                     `json:"display_priority"`
	StarterMessages             []StarterMessage           `json:"starter_messages"`
	Tools                       []agentToolRef             `json:"tools"`
	DocumentSets                []agentDocumentSetRef      `json:"document_sets"`
	Labels                      []agentLabelRef            `json:"labels"`
	Users                       []agentUserRef             `json:"users"`
	Groups                      []int64                    `json:"groups"`
	HierarchyNodes              []agentHierarchyNodeRef    `json:"hierarchy_nodes"`
	AttachedDocuments           []agentAttachedDocumentRef `json:"attached_documents"`
	DefaultModelConfigurationID *int64                     `json:"default_model_configuration_id"`
	SystemPrompt                *string                    `json:"system_prompt"`
	TaskPrompt                  *string                    `json:"task_prompt"`
	DatetimeAware               bool                       `json:"datetime_aware"`
	ReplaceBaseSystemPrompt     bool                       `json:"replace_base_system_prompt"`
}

// ToolIDs returns the ids of the actions attached to the agent.
//
// Onyx hides a few built-in tools from this list, so an agent that holds one
// reports fewer ids than were written.
func (p *Agent) ToolIDs() []int64 {
	ids := make([]int64, 0, len(p.Tools))
	for _, tool := range p.Tools {
		ids = append(ids, tool.ID)
	}
	return ids
}

// DocumentSetIDs returns the ids of the document sets attached to the agent.
func (p *Agent) DocumentSetIDs() []int64 {
	ids := make([]int64, 0, len(p.DocumentSets))
	for _, set := range p.DocumentSets {
		ids = append(ids, set.ID)
	}
	return ids
}

// LabelIDs returns the ids of the labels attached to the agent.
func (p *Agent) LabelIDs() []int64 {
	ids := make([]int64, 0, len(p.Labels))
	for _, label := range p.Labels {
		ids = append(ids, label.ID)
	}
	return ids
}

// UserIDs returns the ids of the users the agent is shared with.
func (p *Agent) UserIDs() []string {
	ids := make([]string, 0, len(p.Users))
	for _, user := range p.Users {
		ids = append(ids, user.ID)
	}
	return ids
}

// HierarchyNodeIDs returns the ids of the folders attached for scoped search.
func (p *Agent) HierarchyNodeIDs() []int64 {
	ids := make([]int64, 0, len(p.HierarchyNodes))
	for _, node := range p.HierarchyNodes {
		ids = append(ids, node.ID)
	}
	return ids
}

// DocumentIDs returns the ids of the documents attached for scoped search.
func (p *Agent) DocumentIDs() []string {
	ids := make([]string, 0, len(p.AttachedDocuments))
	for _, doc := range p.AttachedDocuments {
		ids = append(ids, doc.ID)
	}
	return ids
}

// CreateAgent creates an agent and returns the stored object.
//
// Onyx matches a create by name: a name another live agent holds is rejected,
// and a name held only by a deleted agent revives that agent, id and all. That
// makes the call unsafe to repeat, which the POST rule already covers.
func (c *Client) CreateAgent(ctx context.Context, req AgentWrite) (*Agent, error) {
	var agent Agent
	if err := c.doJSON(ctx, http.MethodPost, "/persona", req, &agent); err != nil {
		return nil, err
	}
	return &agent, nil
}

// GetAgent reads one agent.
//
// A missing or deleted agent answers 400, not 404: the lookup raises a plain
// ValueError, which Onyx renders as a bad request. Callers that need to tell
// "gone" from "failed" use LookupAgent.
func (c *Client) GetAgent(ctx context.Context, id int64) (*Agent, error) {
	var agent Agent
	if err := c.doJSON(ctx, http.MethodGet, fmt.Sprintf("/persona/%d", id), nil, &agent); err != nil {
		return nil, err
	}
	return &agent, nil
}

// LookupAgent reads one agent and reports whether it is still there.
//
// Because a deleted agent answers 400 like any other bad request, a failed
// read is checked against the agent listing rather than against the message
// text, which is not part of the API. The extra call only happens once the
// read has already failed.
func (c *Client) LookupAgent(ctx context.Context, id int64) (*Agent, bool, error) {
	agent, err := c.GetAgent(ctx, id)
	if err == nil {
		return agent, true, nil
	}
	if IsNotFound(err) {
		return nil, false, nil
	}
	listed, listErr := c.agentIsListed(ctx, id)
	if listErr == nil && !listed {
		return nil, false, nil
	}
	return nil, false, err
}

// agentIsListed reports whether the agent listing still holds the id.
func (c *Client) agentIsListed(ctx context.Context, id int64) (bool, error) {
	var agents []Agent
	if err := c.doJSON(ctx, http.MethodGet, "/admin/persona", nil, &agents); err != nil {
		return false, err
	}
	for _, agent := range agents {
		if agent.ID == id {
			return true, nil
		}
	}
	return false, nil
}

// UpdateAgent replaces the agent definition and returns the stored object.
func (c *Client) UpdateAgent(ctx context.Context, id int64, req AgentWrite) (*Agent, error) {
	var agent Agent
	if err := c.doJSON(ctx, http.MethodPatch, fmt.Sprintf("/persona/%d", id), req, &agent); err != nil {
		return nil, err
	}
	return &agent, nil
}

// DeleteAgent deletes an agent.
//
// The row survives as a tombstone: it stops answering reads, but it keeps its
// name and its attached actions. Creating an agent under the same name later
// revives this one rather than making a new one.
func (c *Client) DeleteAgent(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/persona/%d", id), nil, nil)
}

type isListedRequest struct {
	IsListed bool `json:"is_listed"`
}

// SetAgentListed shows or hides an agent in the assistant list. This is its
// own endpoint: neither create nor update carries the flag, and a new agent is
// always listed.
func (c *Client) SetAgentListed(ctx context.Context, id int64, isListed bool) error {
	path := fmt.Sprintf("/admin/persona/%d/listed", id)
	return c.doJSON(ctx, http.MethodPatch, path, isListedRequest{IsListed: isListed}, nil)
}

type displayPriorityRequest struct {
	DisplayPriorityMap map[string]int64 `json:"display_priority_map"`
}

// SetAgentDisplayPriority sets where an agent sorts in the assistant list.
//
// This is its own endpoint because the upsert only reads display_priority when
// it creates an agent; on an update the field is ignored. The endpoint takes a
// map and touches only the agents named in it.
func (c *Client) SetAgentDisplayPriority(ctx context.Context, id, priority int64) error {
	req := displayPriorityRequest{
		DisplayPriorityMap: map[string]int64{strconv.FormatInt(id, 10): priority},
	}
	return c.doJSON(ctx, http.MethodPatch, "/admin/agents/display-priorities", req, nil)
}
