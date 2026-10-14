package client

import (
	"encoding/json"
	"testing"
)

// Onyx renamed this concept to "agent" for users, but the JSON did not follow:
// the API still sends "personas" and "builtin_persona". The Go fields carry the
// new name, so the mapping between the two is load-bearing and invisible —
// Go ignores a key it does not know, which makes a wrong tag decode to a zero
// value instead of an error.
//
// These tests pin the mapping in both directions: the legacy key must populate
// the field, and the new spelling must not.

func TestAgentDecodesLegacyBuiltinKey(t *testing.T) {
	var agent Agent
	if err := json.Unmarshal([]byte(`{"builtin_persona": true}`), &agent); err != nil {
		t.Fatal(err)
	}
	if !agent.BuiltinAgent {
		t.Error(`"builtin_persona" must decode into BuiltinAgent`)
	}

	var renamed Agent
	if err := json.Unmarshal([]byte(`{"builtin_agent": true}`), &renamed); err != nil {
		t.Fatal(err)
	}
	if renamed.BuiltinAgent {
		t.Error(`"builtin_agent" is not a wire name; the API sends "builtin_persona"`)
	}
}

func TestLLMProviderDecodesLegacyAgentsKey(t *testing.T) {
	var view LLMProviderView
	if err := json.Unmarshal([]byte(`{"personas": [8, 9]}`), &view); err != nil {
		t.Fatal(err)
	}
	if len(view.Agents) != 2 {
		t.Errorf(`"personas" must decode into Agents, got %v`, view.Agents)
	}

	var renamed LLMProviderView
	if err := json.Unmarshal([]byte(`{"agents": [8, 9]}`), &renamed); err != nil {
		t.Fatal(err)
	}
	if len(renamed.Agents) != 0 {
		t.Error(`"agents" is not a wire name; the API sends "personas"`)
	}
}

// The upsert request is the write half of the same boundary: the body the
// provider PUTs must spell the field "personas" or Onyx drops the restriction.
func TestLLMProviderUpsertEncodesLegacyAgentsKey(t *testing.T) {
	body, err := json.Marshal(LLMProviderUpsertRequest{Agents: []int64{8}})
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	if err := json.Unmarshal(body, &raw); err != nil {
		t.Fatal(err)
	}
	if _, present := raw["personas"]; !present {
		t.Errorf(`upsert body must send "personas", got %s`, body)
	}
	if _, present := raw["agents"]; present {
		t.Errorf(`upsert body must not send "agents", got %s`, body)
	}
}

func TestUserGroupDecodesLegacyAgentsKey(t *testing.T) {
	var group UserGroup
	if err := json.Unmarshal([]byte(`{"personas": [{"id": 12, "name": "support"}]}`), &group); err != nil {
		t.Fatal(err)
	}
	if len(group.Agents) != 1 {
		t.Errorf(`"personas" must decode into Agents, got %v`, group.Agents)
	}

	var renamed UserGroup
	if err := json.Unmarshal([]byte(`{"agents": [{"id": 12, "name": "support"}]}`), &renamed); err != nil {
		t.Fatal(err)
	}
	if len(renamed.Agents) != 0 {
		t.Error(`"agents" is not a wire name; the API sends "personas"`)
	}
}
