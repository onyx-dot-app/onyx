package client

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

const personaResponse = `{
	"id": 4,
	"name": "support",
	"description": "answers support questions",
	"is_public": true,
	"is_listed": true,
	"is_featured": false,
	"builtin_persona": false,
	"icon_name": null,
	"display_priority": null,
	"starter_messages": [{"name": "Refunds", "message": "How do refunds work?"}],
	"tools": [{"id": 7}, {"id": 9}],
	"document_sets": [{"id": 2}],
	"labels": [{"id": 5}],
	"users": [{"id": "3f2b7c1e-0000-4000-8000-000000000001"}],
	"groups": [11],
	"hierarchy_nodes": [{"id": 21}],
	"attached_documents": [{"id": "doc-1"}],
	"default_model_configuration_id": null,
	"system_prompt": "be helpful",
	"task_prompt": "",
	"datetime_aware": false,
	"replace_base_system_prompt": false
}`

func TestCreatePersonaSendsFullBody(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, personaResponse)
	persona, err := c.CreatePersona(context.Background(), PersonaWrite{
		Name:             "support",
		Description:      "answers support questions",
		DocumentSetIDs:   []int64{2},
		ToolIDs:          []int64{7, 9},
		SystemPrompt:     "be helpful",
		HierarchyNodeIDs: []int64{},
		DocumentIDs:      []string{},
	})
	if err != nil {
		t.Fatal(err)
	}
	if persona.ID != 4 || persona.Name != "support" {
		t.Errorf("unexpected persona: %+v", persona)
	}
	if captured.Method != http.MethodPost || captured.Path != "/persona" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	// Every field the provider owns is sent on every write, so the server's
	// "null means leave unchanged" never applies.
	for _, field := range []string{
		"name", "description", "document_set_ids", "tool_ids", "system_prompt",
		"task_prompt", "datetime_aware", "is_public", "is_featured", "starter_messages",
		"label_ids", "users", "groups", "hierarchy_node_ids", "document_ids",
	} {
		if _, ok := body[field]; !ok {
			t.Errorf("%s must be present: the write is a full replace", field)
		}
	}
}

func TestUpdatePersonaUsesPatchWithIDInPath(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, personaResponse)
	if _, err := c.UpdatePersona(context.Background(), 4, PersonaWrite{Name: "support"}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/persona/4" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}

func TestGetPersonaAndDelete(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, personaResponse)
	if _, err := c.GetPersona(context.Background(), 4); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/persona/4" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}

	c, captured = newTestServer(t, http.StatusOK, `null`)
	if err := c.DeletePersona(context.Background(), 4); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/persona/4" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}

// is_listed is not on the upsert body; it has an admin-only endpoint.
func TestSetPersonaListed(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.SetPersonaListed(context.Background(), 4, false); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/persona/4/listed" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	if bodyAsMap(t, captured.Body)["is_listed"] != false {
		t.Errorf("unexpected body: %s", captured.Body)
	}
}

// The snapshot nests each relation as an object, so the ids the provider
// stores have to be pulled out of them.
func TestPersonaIDAccessors(t *testing.T) {
	c, _ := newTestServer(t, http.StatusOK, personaResponse)
	persona, err := c.GetPersona(context.Background(), 4)
	if err != nil {
		t.Fatal(err)
	}
	if got := persona.ToolIDs(); len(got) != 2 || got[0] != 7 || got[1] != 9 {
		t.Errorf("ToolIDs() = %v, want [7 9]", got)
	}
	if got := persona.DocumentSetIDs(); len(got) != 1 || got[0] != 2 {
		t.Errorf("DocumentSetIDs() = %v, want [2]", got)
	}
	if got := persona.LabelIDs(); len(got) != 1 || got[0] != 5 {
		t.Errorf("LabelIDs() = %v, want [5]", got)
	}
	if got := persona.UserIDs(); len(got) != 1 || got[0] != "3f2b7c1e-0000-4000-8000-000000000001" {
		t.Errorf("UserIDs() = %v", got)
	}
	if got := persona.HierarchyNodeIDs(); len(got) != 1 || got[0] != 21 {
		t.Errorf("HierarchyNodeIDs() = %v, want [21]", got)
	}
	if got := persona.DocumentIDs(); len(got) != 1 || got[0] != "doc-1" {
		t.Errorf("DocumentIDs() = %v, want [doc-1]", got)
	}
}

// A deleted agent answers 400, not 404, so "gone" cannot be read off the
// status alone. LookupPersona confirms against the listing instead.
func TestLookupPersonaTreatsAMissingAgentAsGone(t *testing.T) {
	for _, tc := range []struct {
		name      string
		listBody  string
		wantFound bool
		wantErr   bool
	}{
		{"absent from the listing", `[{"id": 9}]`, false, false},
		{"still listed", `[{"id": 4}]`, false, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				if r.URL.Path == "/admin/persona" {
					_, _ = w.Write([]byte(tc.listBody))
					return
				}
				w.WriteHeader(http.StatusBadRequest)
				_, _ = w.Write([]byte(`{"message": "Persona with ID 4 does not exist"}`))
			}))
			defer server.Close()

			_, found, err := newFastRetryClient(server.URL).LookupPersona(context.Background(), 4)
			if found != tc.wantFound {
				t.Errorf("found = %v, want %v", found, tc.wantFound)
			}
			if (err != nil) != tc.wantErr {
				t.Errorf("err = %v, wantErr %v", err, tc.wantErr)
			}
		})
	}
}

// The upsert ignores display_priority once the agent exists, so it has to go
// through the endpoint that takes a map of agent id to priority.
func TestSetPersonaDisplayPriority(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.SetPersonaDisplayPriority(context.Background(), 4, 2); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/agents/display-priorities" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	priorities, ok := bodyAsMap(t, captured.Body)["display_priority_map"].(map[string]any)
	if !ok {
		t.Fatalf("unexpected body: %s", captured.Body)
	}
	if priorities["4"] != float64(2) {
		t.Errorf("display_priority_map = %v, want {\"4\": 2}", priorities)
	}
}
