package parser

import (
	"encoding/json"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func TestEmptyLineReturnsNil(t *testing.T) {
	for _, line := range []string{"", "  ", "\n"} {
		if ParseStreamLine(line) != nil {
			t.Errorf("expected nil for %q", line)
		}
	}
}

func TestInvalidJSONReturnsErrorEvent(t *testing.T) {
	for _, line := range []string{"not json", "{broken"} {
		event := ParseStreamLine(line)
		if event == nil {
			t.Errorf("expected ErrorEvent for %q, got nil", line)
			continue
		}
		if _, ok := event.(models.ErrorEvent); !ok {
			t.Errorf("expected ErrorEvent for %q, got %T", line, event)
		}
	}
}

func TestSessionCreated(t *testing.T) {
	line := mustJSON(map[string]interface{}{
		"chat_session_id": "550e8400-e29b-41d4-a716-446655440000",
	})
	event := ParseStreamLine(line)
	e, ok := event.(models.SessionCreatedEvent)
	if !ok {
		t.Fatalf("expected SessionCreatedEvent, got %T", event)
	}
	if e.ChatSessionID != "550e8400-e29b-41d4-a716-446655440000" {
		t.Errorf("got %s", e.ChatSessionID)
	}
}

func TestMessageIDInfo(t *testing.T) {
	line := mustJSON(map[string]interface{}{
		"user_message_id":              1,
		"reserved_assistant_message_id": 2,
	})
	event := ParseStreamLine(line)
	e, ok := event.(models.MessageIDEvent)
	if !ok {
		t.Fatalf("expected MessageIDEvent, got %T", event)
	}
	if e.UserMessageID == nil || *e.UserMessageID != 1 {
		t.Errorf("expected user_message_id=1")
	}
	if e.ReservedAgentMessageID != 2 {
		t.Errorf("got %d", e.ReservedAgentMessageID)
	}
}

func TestMessageIDInfoNullUserID(t *testing.T) {
	line := mustJSON(map[string]interface{}{
		"user_message_id":              nil,
		"reserved_assistant_message_id": 5,
	})
	event := ParseStreamLine(line)
	e, ok := event.(models.MessageIDEvent)
	if !ok {
		t.Fatalf("expected MessageIDEvent, got %T", event)
	}
	if e.UserMessageID != nil {
		t.Error("expected nil user_message_id")
	}
	if e.ReservedAgentMessageID != 5 {
		t.Errorf("got %d", e.ReservedAgentMessageID)
	}
}

func TestTopLevelError(t *testing.T) {
	line := mustJSON(map[string]interface{}{
		"error":        "Rate limit exceeded",
		"stack_trace":  "...",
		"is_retryable": true,
	})
	event := ParseStreamLine(line)
	e, ok := event.(models.ErrorEvent)
	if !ok {
		t.Fatalf("expected ErrorEvent, got %T", event)
	}
	if e.Error != "Rate limit exceeded" {
		t.Errorf("got %s", e.Error)
	}
	if e.StackTrace == nil || *e.StackTrace != "..." {
		t.Error("expected stack_trace")
	}
	if !e.IsRetryable {
		t.Error("expected retryable")
	}
}

func TestTopLevelErrorMinimal(t *testing.T) {
	line := mustJSON(map[string]interface{}{
		"error": "Something broke",
	})
	event := ParseStreamLine(line)
	e, ok := event.(models.ErrorEvent)
	if !ok {
		t.Fatalf("expected ErrorEvent, got %T", event)
	}
	if e.Error != "Something broke" {
		t.Errorf("got %s", e.Error)
	}
	if !e.IsRetryable {
		t.Error("expected default retryable=true")
	}
}

func makePacket(obj map[string]interface{}, turnIndex, tabIndex int) string {
	return mustJSON(map[string]interface{}{
		"placement": map[string]interface{}{"turn_index": turnIndex, "tab_index": tabIndex},
		"obj":       obj,
	})
}

func TestStopPacket(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "stop", "stop_reason": "completed"}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.StopEvent)
	if !ok {
		t.Fatalf("expected StopEvent, got %T", event)
	}
	if e.StopReason == nil || *e.StopReason != "completed" {
		t.Error("expected stop_reason=completed")
	}
	if e.Placement == nil || e.Placement.TurnIndex != 0 {
		t.Error("expected placement")
	}
}

func TestStopPacketNoReason(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "stop"}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.StopEvent)
	if !ok {
		t.Fatalf("expected StopEvent, got %T", event)
	}
	if e.StopReason != nil {
		t.Error("expected nil stop_reason")
	}
}

func TestMessageStart(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "message_start"}, 0, 0)
	event := ParseStreamLine(line)
	_, ok := event.(models.MessageStartEvent)
	if !ok {
		t.Fatalf("expected MessageStartEvent, got %T", event)
	}
}

func TestMessageStartWithDocuments(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "message_start",
		"final_documents": []interface{}{
			map[string]interface{}{"document_id": "doc1", "semantic_identifier": "Doc 1"},
		},
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.MessageStartEvent)
	if !ok {
		t.Fatalf("expected MessageStartEvent, got %T", event)
	}
	if len(e.Documents) != 1 || e.Documents[0].DocumentID != "doc1" {
		t.Error("expected 1 document with id doc1")
	}
}

func TestMessageDelta(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "message_delta", "content": "Hello"}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.MessageDeltaEvent)
	if !ok {
		t.Fatalf("expected MessageDeltaEvent, got %T", event)
	}
	if e.Content != "Hello" {
		t.Errorf("got %s", e.Content)
	}
}

func TestMessageDeltaEmpty(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "message_delta", "content": ""}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.MessageDeltaEvent)
	if !ok {
		t.Fatalf("expected MessageDeltaEvent, got %T", event)
	}
	if e.Content != "" {
		t.Errorf("expected empty, got %s", e.Content)
	}
}

func TestSearchToolStart(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "search_tool_start", "is_internet_search": true,
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.SearchStartEvent)
	if !ok {
		t.Fatalf("expected SearchStartEvent, got %T", event)
	}
	if !e.IsInternetSearch {
		t.Error("expected internet search")
	}
}

func TestSearchToolQueries(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type":    "search_tool_queries_delta",
		"queries": []interface{}{"query 1", "query 2"},
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.SearchQueriesEvent)
	if !ok {
		t.Fatalf("expected SearchQueriesEvent, got %T", event)
	}
	if len(e.Queries) != 2 || e.Queries[0] != "query 1" {
		t.Error("unexpected queries")
	}
}

func TestSearchToolDocuments(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "search_tool_documents_delta",
		"documents": []interface{}{
			map[string]interface{}{"document_id": "d1", "semantic_identifier": "First Doc", "link": "http://example.com"},
			map[string]interface{}{"document_id": "d2", "semantic_identifier": "Second Doc"},
		},
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.SearchDocumentsEvent)
	if !ok {
		t.Fatalf("expected SearchDocumentsEvent, got %T", event)
	}
	if len(e.Documents) != 2 {
		t.Errorf("expected 2 docs, got %d", len(e.Documents))
	}
	if e.Documents[0].Link == nil || *e.Documents[0].Link != "http://example.com" {
		t.Error("expected link on first doc")
	}
}

func TestReasoningStart(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "reasoning_start"}, 0, 0)
	event := ParseStreamLine(line)
	if _, ok := event.(models.ReasoningStartEvent); !ok {
		t.Fatalf("expected ReasoningStartEvent, got %T", event)
	}
}

func TestReasoningDelta(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "reasoning_delta", "reasoning": "Let me think...",
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.ReasoningDeltaEvent)
	if !ok {
		t.Fatalf("expected ReasoningDeltaEvent, got %T", event)
	}
	if e.Reasoning != "Let me think..." {
		t.Errorf("got %s", e.Reasoning)
	}
}

func TestReasoningDone(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "reasoning_done"}, 0, 0)
	event := ParseStreamLine(line)
	if _, ok := event.(models.ReasoningDoneEvent); !ok {
		t.Fatalf("expected ReasoningDoneEvent, got %T", event)
	}
}

func TestCitationInfo(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "citation_info", "citation_number": 1, "document_id": "doc_abc",
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.CitationEvent)
	if !ok {
		t.Fatalf("expected CitationEvent, got %T", event)
	}
	if e.CitationNumber != 1 || e.DocumentID != "doc_abc" {
		t.Errorf("got %d, %s", e.CitationNumber, e.DocumentID)
	}
}

func TestOpenURLStart(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "open_url_start"}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.ToolStartEvent)
	if !ok {
		t.Fatalf("expected ToolStartEvent, got %T", event)
	}
	if e.Type != "open_url_start" {
		t.Errorf("got type %s", e.Type)
	}
}

func TestPythonToolStart(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "python_tool_start", "code": "print('hi')",
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.ToolStartEvent)
	if !ok {
		t.Fatalf("expected ToolStartEvent, got %T", event)
	}
	if e.ToolName != "Python Tool" {
		t.Errorf("got %s", e.ToolName)
	}
}

func TestCustomToolStart(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "custom_tool_start", "tool_name": "MyTool",
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.ToolStartEvent)
	if !ok {
		t.Fatalf("expected ToolStartEvent, got %T", event)
	}
	if e.ToolName != "MyTool" {
		t.Errorf("got %s", e.ToolName)
	}
}

func TestDeepResearchPlanDelta(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "deep_research_plan_delta", "content": "Step 1: ...",
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.DeepResearchPlanDeltaEvent)
	if !ok {
		t.Fatalf("expected DeepResearchPlanDeltaEvent, got %T", event)
	}
	if e.Content != "Step 1: ..." {
		t.Errorf("got %s", e.Content)
	}
}

func TestResearchAgentStart(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "research_agent_start", "research_task": "Find info about X",
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.ResearchAgentStartEvent)
	if !ok {
		t.Fatalf("expected ResearchAgentStartEvent, got %T", event)
	}
	if e.ResearchTask != "Find info about X" {
		t.Errorf("got %s", e.ResearchTask)
	}
}

func TestIntermediateReportDelta(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "intermediate_report_delta", "content": "Report text",
	}, 0, 0)
	event := ParseStreamLine(line)
	e, ok := event.(models.IntermediateReportDeltaEvent)
	if !ok {
		t.Fatalf("expected IntermediateReportDeltaEvent, got %T", event)
	}
	if e.Content != "Report text" {
		t.Errorf("got %s", e.Content)
	}
}

func TestUnknownPacketType(t *testing.T) {
	line := makePacket(map[string]interface{}{"type": "section_end"}, 0, 0)
	event := ParseStreamLine(line)
	if _, ok := event.(models.UnknownEvent); !ok {
		t.Fatalf("expected UnknownEvent, got %T", event)
	}
}

func TestUnknownTopLevel(t *testing.T) {
	line := mustJSON(map[string]interface{}{"some_unknown_field": "value"})
	event := ParseStreamLine(line)
	if _, ok := event.(models.UnknownEvent); !ok {
		t.Fatalf("expected UnknownEvent, got %T", event)
	}
}

func TestPlacementPreserved(t *testing.T) {
	line := makePacket(map[string]interface{}{
		"type": "message_delta", "content": "x",
	}, 3, 1)
	event := ParseStreamLine(line)
	e, ok := event.(models.MessageDeltaEvent)
	if !ok {
		t.Fatalf("expected MessageDeltaEvent, got %T", event)
	}
	if e.Placement == nil {
		t.Fatal("expected placement")
	}
	if e.Placement.TurnIndex != 3 || e.Placement.TabIndex != 1 {
		t.Errorf("got turn=%d tab=%d", e.Placement.TurnIndex, e.Placement.TabIndex)
	}
}

func mustJSON(v interface{}) string {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return string(b)
}
