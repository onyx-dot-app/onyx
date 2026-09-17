package parser

import (
	"encoding/json"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"testing"
)

func TestControlMessages(t *testing.T) {
	for _, test := range []struct{ line, kind string }{
		{`{"chat_session_id":"session"}`, models.EventSessionCreated},
		{`{"user_message_id":null,"reserved_assistant_message_id":5}`, models.EventMessageIDInfo},
		{`{"error":"denied","is_retryable":false}`, models.EventError},
		{`{"obj":{"type":"stop","stop_reason":"finished"}}`, models.EventStop},
		{`{"obj":{"type":"chat_heartbeat"}}`, models.EventHeartbeat},
		{`{"obj":{"type":"run_update","status":"complete"}}`, models.EventRunUpdate},
	} {
		event := ParseStreamLine(test.line)
		if event == nil || event.EventType() != test.kind {
			t.Fatalf("%s: got %v", test.line, event)
		}
	}
}
func TestMalformedStreamFails(t *testing.T) {
	for _, line := range []string{`not json`, `{"obj":5}`, `{"obj":{"type":"item_update","item":{"kind":"text"}}}`} {
		if _, ok := ParseStreamLine(line).(models.ErrorEvent); !ok {
			t.Fatalf("expected error for %s", line)
		}
	}
	for _, line := range []string{"", " \n"} {
		if ParseStreamLine(line) != nil {
			t.Fatalf("expected no event for %q", line)
		}
	}
}
func TestItemRetainsIdentityAndToolMetadata(t *testing.T) {
	event := ParseStreamLine(`{"model_index":2,"identity":{"response_id":3,"run_id":"child","message_id":"m","part_id":"tool","tool_call_id":"call","parent_run_id":"root","parent_message_id":"parent","parent_tool_call_id":"spawn"},"obj":{"type":"item_update","item":{"kind":"tool","name":"custom","status":"complete","arguments":{"query":"value"},"metadata":{"type":"custom_tool_result","tool_result":{"nested":[1,2]}},"output":"done"}}}`)
	item, ok := event.(models.ItemUpdateEvent)
	if !ok {
		t.Fatalf("got %T", event)
	}
	if item.Identity.ParentToolCallID != "spawn" || item.ModelIndex == nil || *item.ModelIndex != 2 {
		t.Fatalf("lost identity: %+v", item)
	}
	var metadata struct {
		ToolResult struct {
			Nested []int `json:"nested"`
		} `json:"tool_result"`
	}
	if err := json.Unmarshal(item.Item.Metadata, &metadata); err != nil {
		t.Fatal(err)
	}
	if len(metadata.ToolResult.Nested) != 2 {
		t.Fatal("tool metadata lost")
	}
}
func TestLiveAndSavedItemsHaveSameContent(t *testing.T) {
	lines := []string{
		`{"identity":{"response_id":1,"run_id":"r","message_id":"m","part_id":"answer"},"obj":{"type":"item_update","item":{"kind":"text","status":"running","purpose":"answer","text":""}}}`,
		`{"identity":{"response_id":1,"run_id":"r","message_id":"m","part_id":"answer"},"obj":{"type":"item_delta","delta":{"kind":"text","text":"Hello","citations":[{"citation_number":1,"document_id":"d"}]}}}`,
		`{"identity":{"response_id":1,"run_id":"r","message_id":"m","part_id":"answer"},"obj":{"type":"item_update","item":{"kind":"text","status":"complete","purpose":"answer","text":"Hello","citations":[{"citation_number":1,"document_id":"d"}]}}}`,
	}
	var live, saved models.ResponseState
	printed := ""
	for _, line := range lines {
		change, err := live.Apply(ParseStreamLine(line))
		if err != nil {
			t.Fatal(err)
		}
		printed += change.TextDelta()
	}
	if _, err := saved.Apply(ParseStreamLine(lines[len(lines)-1])); err != nil {
		t.Fatal(err)
	}
	if live.Text() != "Hello" || live.Text() != saved.Text() || printed != "Hello" {
		t.Fatalf("duplicated output: %q, %q", live.Text(), printed)
	}
	if live.Citations()[1] != "d" {
		t.Fatal("citation missing")
	}
}
func TestDeltaWithoutItemFails(t *testing.T) {
	var state models.ResponseState
	event := ParseStreamLine(`{"identity":{"response_id":1,"run_id":"r","message_id":"m","part_id":"answer"},"obj":{"type":"item_delta","delta":{"kind":"text","text":"orphan"}}}`)
	if _, err := state.Apply(event); err == nil {
		t.Fatal("expected missing-item error")
	}
}

func TestSearchSnapshotsReplaceMetadataWithoutRepeatedActivity(t *testing.T) {
	var state models.ResponseState
	line := `{"identity":{"response_id":1,"run_id":"r","message_id":"m","part_id":"tool","tool_call_id":"s"},"obj":{"type":"item_update","item":{"kind":"tool","name":"web_search","status":"running","metadata":{"type":"search_result","queries":["expanded query"],"search_docs":[{"document_id":"d"}]}}}}`
	change, err := state.Apply(ParseStreamLine(line))
	if err != nil {
		t.Fatal(err)
	}
	activity, err := change.Activity()
	if err != nil {
		t.Fatal(err)
	}
	if len(activity) != 3 {
		t.Fatalf("expected start, query and documents: %v", activity)
	}
	change, err = state.Apply(ParseStreamLine(line))
	if err != nil {
		t.Fatal(err)
	}
	activity, err = change.Activity()
	if err != nil {
		t.Fatal(err)
	}
	if len(activity) != 0 {
		t.Fatalf("repeated unchanged activity: %v", activity)
	}
}
