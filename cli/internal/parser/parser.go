// Package parser handles NDJSON stream parsing for Onyx chat responses.
package parser

import (
	"encoding/json"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// ParseStreamLine parses a single NDJSON line into a typed StreamEvent.
// Returns nil for empty lines or unparseable content.
func ParseStreamLine(line string) models.StreamEvent {
	line = strings.TrimSpace(line)
	if line == "" {
		return nil
	}

	var data map[string]interface{}
	if err := json.Unmarshal([]byte(line), &data); err != nil {
		return nil
	}

	// Case 1: CreateChatSessionID
	if _, ok := data["chat_session_id"]; ok {
		if _, hasPlacement := data["placement"]; !hasPlacement {
			sid, _ := data["chat_session_id"].(string)
			return models.SessionCreatedEvent{ChatSessionID: sid}
		}
	}

	// Case 2: MessageResponseIDInfo
	if _, ok := data["reserved_assistant_message_id"]; ok {
		reservedID := jsonInt(data["reserved_assistant_message_id"])
		var userMsgID *int
		if v, ok := data["user_message_id"]; ok && v != nil {
			id := jsonInt(v)
			userMsgID = &id
		}
		return models.MessageIDEvent{
			UserMessageID:              userMsgID,
			ReservedAssistantMessageID: reservedID,
		}
	}

	// Case 3: StreamingError (top-level error without placement)
	if _, ok := data["error"]; ok {
		if _, hasPlacement := data["placement"]; !hasPlacement {
			errStr, _ := data["error"].(string)
			var stackTrace *string
			if st, ok := data["stack_trace"].(string); ok {
				stackTrace = &st
			}
			isRetryable := true
			if v, ok := data["is_retryable"].(bool); ok {
				isRetryable = v
			}
			return models.ErrorEvent{
				Error:       errStr,
				StackTrace:  stackTrace,
				IsRetryable: isRetryable,
			}
		}
	}

	// Case 4: Packet with placement + obj
	if rawPlacement, ok := data["placement"]; ok {
		if rawObj, ok := data["obj"]; ok {
			placement := parsePlacement(rawPlacement)
			obj, _ := rawObj.(map[string]interface{})
			if obj == nil {
				return models.UnknownEvent{Placement: placement, RawData: data}
			}
			return parsePacketObj(obj, placement)
		}
	}

	// Fallback
	return models.UnknownEvent{RawData: data}
}

func parsePlacement(raw interface{}) *models.Placement {
	m, ok := raw.(map[string]interface{})
	if !ok {
		return nil
	}
	p := &models.Placement{
		TurnIndex: jsonInt(m["turn_index"]),
		TabIndex:  jsonInt(m["tab_index"]),
	}
	if v, ok := m["sub_turn_index"]; ok && v != nil {
		st := jsonInt(v)
		p.SubTurnIndex = &st
	}
	return p
}

func parsePacketObj(obj map[string]interface{}, placement *models.Placement) models.StreamEvent {
	objType, _ := obj["type"].(string)

	switch objType {
	case "stop":
		var reason *string
		if r, ok := obj["stop_reason"].(string); ok {
			reason = &r
		}
		return models.StopEvent{Placement: placement, StopReason: reason}

	case "error":
		errMsg := "Unknown error"
		if e, ok := obj["exception"]; ok {
			errMsg = toString(e)
		}
		return models.ErrorEvent{Placement: placement, Error: errMsg, IsRetryable: true}

	case "message_start":
		var docs []models.SearchDoc
		if rawDocs, ok := obj["final_documents"].([]interface{}); ok {
			docs = parseSearchDocs(rawDocs)
		}
		return models.MessageStartEvent{Placement: placement, Documents: docs}

	case "message_delta":
		content, _ := obj["content"].(string)
		return models.MessageDeltaEvent{Placement: placement, Content: content}

	case "search_tool_start":
		isInternet, _ := obj["is_internet_search"].(bool)
		return models.SearchStartEvent{Placement: placement, IsInternetSearch: isInternet}

	case "search_tool_queries_delta":
		var queries []string
		if raw, ok := obj["queries"].([]interface{}); ok {
			for _, q := range raw {
				if s, ok := q.(string); ok {
					queries = append(queries, s)
				}
			}
		}
		return models.SearchQueriesEvent{Placement: placement, Queries: queries}

	case "search_tool_documents_delta":
		var docs []models.SearchDoc
		if rawDocs, ok := obj["documents"].([]interface{}); ok {
			docs = parseSearchDocs(rawDocs)
		}
		return models.SearchDocumentsEvent{Placement: placement, Documents: docs}

	case "reasoning_start":
		return models.ReasoningStartEvent{Placement: placement}

	case "reasoning_delta":
		reasoning, _ := obj["reasoning"].(string)
		return models.ReasoningDeltaEvent{Placement: placement, Reasoning: reasoning}

	case "reasoning_done":
		return models.ReasoningDoneEvent{Placement: placement}

	case "citation_info":
		return models.CitationEvent{
			Placement:      placement,
			CitationNumber: jsonInt(obj["citation_number"]),
			DocumentID:     jsonString(obj["document_id"]),
		}

	case "open_url_start", "image_generation_start", "python_tool_start", "file_reader_start":
		toolName := strings.ReplaceAll(strings.TrimSuffix(objType, "_start"), "_", " ")
		toolName = strings.Title(toolName) //nolint:staticcheck
		return models.ToolStartEvent{Placement: placement, Type: objType, ToolName: toolName}

	case "custom_tool_start":
		toolName := jsonString(obj["tool_name"])
		if toolName == "" {
			toolName = "Custom Tool"
		}
		return models.ToolStartEvent{Placement: placement, Type: models.EventCustomToolStart, ToolName: toolName}

	case "deep_research_plan_start":
		return models.DeepResearchPlanStartEvent{Placement: placement}

	case "deep_research_plan_delta":
		content, _ := obj["content"].(string)
		return models.DeepResearchPlanDeltaEvent{Placement: placement, Content: content}

	case "research_agent_start":
		task, _ := obj["research_task"].(string)
		return models.ResearchAgentStartEvent{Placement: placement, ResearchTask: task}

	case "intermediate_report_start":
		return models.IntermediateReportStartEvent{Placement: placement}

	case "intermediate_report_delta":
		content, _ := obj["content"].(string)
		return models.IntermediateReportDeltaEvent{Placement: placement, Content: content}

	default:
		return models.UnknownEvent{Placement: placement, RawData: obj}
	}
}

func parseSearchDocs(raw []interface{}) []models.SearchDoc {
	var docs []models.SearchDoc
	for _, item := range raw {
		m, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		doc := models.SearchDoc{
			DocumentID:         jsonString(m["document_id"]),
			SemanticIdentifier: jsonString(m["semantic_identifier"]),
			SourceType:         jsonString(m["source_type"]),
		}
		if link, ok := m["link"].(string); ok {
			doc.Link = &link
		}
		docs = append(docs, doc)
	}
	return docs
}

func jsonInt(v interface{}) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	default:
		return 0
	}
}

func jsonString(v interface{}) string {
	s, _ := v.(string)
	return s
}

func toString(v interface{}) string {
	switch s := v.(type) {
	case string:
		return s
	default:
		b, _ := json.Marshal(v)
		return string(b)
	}
}
