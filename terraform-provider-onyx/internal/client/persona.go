package client

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
)

// StarterMessage is one suggested opening prompt shown on an agent's card.
type StarterMessage struct {
	Name    string `json:"name"`
	Message string `json:"message"`
}

// PersonaWrite mirrors PersonaUpsertRequest, which both create and update take.
//
// Several fields are nullable server-side, where null means "leave unchanged"
// rather than "clear". The provider manages the whole agent, so it sends every
// value it owns on every write and the tri-state never comes into play.
//
// HierarchyNodeIDs and DocumentIDs are the exception: Terraform does not manage
// them, but they default to an empty list when omitted, which would clear
// attachments made in the admin panel. Update reads the stored values and
// sends them back.
type PersonaWrite struct {
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

type personaToolRef struct {
	ID int64 `json:"id"`
}

type personaDocumentSetRef struct {
	ID int64 `json:"id"`
}

type personaLabelRef struct {
	ID int64 `json:"id"`
}

type personaUserRef struct {
	ID string `json:"id"`
}

type personaHierarchyNodeRef struct {
	ID int64 `json:"id"`
}

type personaAttachedDocumentRef struct {
	ID string `json:"id"`
}

// Persona mirrors PersonaSnapshot.
//
// The snapshot carries no search_start_date, so that field cannot be read back.
type Persona struct {
	ID                          int64                        `json:"id"`
	Name                        string                       `json:"name"`
	Description                 string                       `json:"description"`
	IsPublic                    bool                         `json:"is_public"`
	IsListed                    bool                         `json:"is_listed"`
	IsFeatured                  bool                         `json:"is_featured"`
	BuiltinPersona              bool                         `json:"builtin_persona"`
	IconName                    *string                      `json:"icon_name"`
	DisplayPriority             *int64                       `json:"display_priority"`
	StarterMessages             []StarterMessage             `json:"starter_messages"`
	Tools                       []personaToolRef             `json:"tools"`
	DocumentSets                []personaDocumentSetRef      `json:"document_sets"`
	Labels                      []personaLabelRef            `json:"labels"`
	Users                       []personaUserRef             `json:"users"`
	Groups                      []int64                      `json:"groups"`
	HierarchyNodes              []personaHierarchyNodeRef    `json:"hierarchy_nodes"`
	AttachedDocuments           []personaAttachedDocumentRef `json:"attached_documents"`
	DefaultModelConfigurationID *int64                       `json:"default_model_configuration_id"`
	SystemPrompt                *string                      `json:"system_prompt"`
	TaskPrompt                  *string                      `json:"task_prompt"`
	DatetimeAware               bool                         `json:"datetime_aware"`
	ReplaceBaseSystemPrompt     bool                         `json:"replace_base_system_prompt"`
}

// ToolIDs returns the ids of the actions attached to the agent.
//
// Onyx hides a few built-in tools from this list, so an agent that holds one
// reports fewer ids than were written.
func (p *Persona) ToolIDs() []int64 {
	ids := make([]int64, 0, len(p.Tools))
	for _, tool := range p.Tools {
		ids = append(ids, tool.ID)
	}
	return ids
}

// DocumentSetIDs returns the ids of the document sets attached to the agent.
func (p *Persona) DocumentSetIDs() []int64 {
	ids := make([]int64, 0, len(p.DocumentSets))
	for _, set := range p.DocumentSets {
		ids = append(ids, set.ID)
	}
	return ids
}

// LabelIDs returns the ids of the labels attached to the agent.
func (p *Persona) LabelIDs() []int64 {
	ids := make([]int64, 0, len(p.Labels))
	for _, label := range p.Labels {
		ids = append(ids, label.ID)
	}
	return ids
}

// UserIDs returns the ids of the users the agent is shared with.
func (p *Persona) UserIDs() []string {
	ids := make([]string, 0, len(p.Users))
	for _, user := range p.Users {
		ids = append(ids, user.ID)
	}
	return ids
}

// HierarchyNodeIDs returns the ids of the folders attached for scoped search.
func (p *Persona) HierarchyNodeIDs() []int64 {
	ids := make([]int64, 0, len(p.HierarchyNodes))
	for _, node := range p.HierarchyNodes {
		ids = append(ids, node.ID)
	}
	return ids
}

// DocumentIDs returns the ids of the documents attached for scoped search.
func (p *Persona) DocumentIDs() []string {
	ids := make([]string, 0, len(p.AttachedDocuments))
	for _, doc := range p.AttachedDocuments {
		ids = append(ids, doc.ID)
	}
	return ids
}

// CreatePersona creates an agent and returns the stored object.
//
// Onyx matches a create by name: a name another live agent holds is rejected,
// and a name held only by a deleted agent revives that agent, id and all. That
// makes the call unsafe to repeat, which the POST rule already covers.
func (c *Client) CreatePersona(ctx context.Context, req PersonaWrite) (*Persona, error) {
	var persona Persona
	if err := c.doJSON(ctx, http.MethodPost, "/persona", req, &persona); err != nil {
		return nil, err
	}
	return &persona, nil
}

// GetPersona reads one agent.
//
// A missing or deleted agent answers 400, not 404: the lookup raises a plain
// ValueError, which Onyx renders as a bad request. Callers that need to tell
// "gone" from "failed" use LookupPersona.
func (c *Client) GetPersona(ctx context.Context, id int64) (*Persona, error) {
	var persona Persona
	if err := c.doJSON(ctx, http.MethodGet, fmt.Sprintf("/persona/%d", id), nil, &persona); err != nil {
		return nil, err
	}
	return &persona, nil
}

// LookupPersona reads one agent and reports whether it is still there.
//
// Because a deleted agent answers 400 like any other bad request, a failed
// read is checked against the agent listing rather than against the message
// text, which is not part of the API. The extra call only happens once the
// read has already failed.
func (c *Client) LookupPersona(ctx context.Context, id int64) (*Persona, bool, error) {
	persona, err := c.GetPersona(ctx, id)
	if err == nil {
		return persona, true, nil
	}
	if IsNotFound(err) {
		return nil, false, nil
	}
	listed, listErr := c.personaIsListed(ctx, id)
	if listErr == nil && !listed {
		return nil, false, nil
	}
	return nil, false, err
}

// personaIsListed reports whether the agent listing still holds the id.
func (c *Client) personaIsListed(ctx context.Context, id int64) (bool, error) {
	var personas []Persona
	if err := c.doJSON(ctx, http.MethodGet, "/admin/persona", nil, &personas); err != nil {
		return false, err
	}
	for _, persona := range personas {
		if persona.ID == id {
			return true, nil
		}
	}
	return false, nil
}

// UpdatePersona replaces the agent definition and returns the stored object.
func (c *Client) UpdatePersona(ctx context.Context, id int64, req PersonaWrite) (*Persona, error) {
	var persona Persona
	if err := c.doJSON(ctx, http.MethodPatch, fmt.Sprintf("/persona/%d", id), req, &persona); err != nil {
		return nil, err
	}
	return &persona, nil
}

// DeletePersona deletes an agent.
//
// The row survives as a tombstone: it stops answering reads, but it keeps its
// name and its attached actions. Creating an agent under the same name later
// revives this one rather than making a new one.
func (c *Client) DeletePersona(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/persona/%d", id), nil, nil)
}

type isListedRequest struct {
	IsListed bool `json:"is_listed"`
}

// SetPersonaListed shows or hides an agent in the assistant list. This is its
// own endpoint: neither create nor update carries the flag, and a new agent is
// always listed.
func (c *Client) SetPersonaListed(ctx context.Context, id int64, isListed bool) error {
	path := fmt.Sprintf("/admin/persona/%d/listed", id)
	return c.doJSON(ctx, http.MethodPatch, path, isListedRequest{IsListed: isListed}, nil)
}

type displayPriorityRequest struct {
	DisplayPriorityMap map[string]int64 `json:"display_priority_map"`
}

// SetPersonaDisplayPriority sets where an agent sorts in the assistant list.
//
// This is its own endpoint because the upsert only reads display_priority when
// it creates an agent; on an update the field is ignored. The endpoint takes a
// map and touches only the agents named in it.
func (c *Client) SetPersonaDisplayPriority(ctx context.Context, id, priority int64) error {
	req := displayPriorityRequest{
		DisplayPriorityMap: map[string]int64{strconv.FormatInt(id, 10): priority},
	}
	return c.doJSON(ctx, http.MethodPatch, "/admin/agents/display-priorities", req, nil)
}
