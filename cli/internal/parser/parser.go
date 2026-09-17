// Package parser decodes the Onyx NDJSON response stream.
package parser

import (
	"encoding/json"
	"fmt"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"strings"
)

type envelope struct {
	models.EventContext
	ChatSessionID          *string         `json:"chat_session_id"`
	UserMessageID          *int            `json:"user_message_id"`
	ReservedAgentMessageID *int            `json:"reserved_assistant_message_id"`
	Error                  *string         `json:"error"`
	StackTrace             *string         `json:"stack_trace"`
	IsRetryable            *bool           `json:"is_retryable"`
	Obj                    json.RawMessage `json:"obj"`
}

func ParseStreamLine(line string) models.StreamEvent {
	if strings.TrimSpace(line) == "" {
		return nil
	}
	var data envelope
	if err := json.Unmarshal([]byte(line), &data); err != nil {
		return malformed(err)
	}
	if data.ChatSessionID != nil {
		return models.SessionCreatedEvent{ChatSessionID: *data.ChatSessionID}
	}
	if data.ReservedAgentMessageID != nil {
		return models.MessageIDEvent{UserMessageID: data.UserMessageID, ReservedAgentMessageID: *data.ReservedAgentMessageID}
	}
	if data.Error != nil {
		return models.ErrorEvent{Error: *data.Error, StackTrace: data.StackTrace, IsRetryable: data.IsRetryable == nil || *data.IsRetryable}
	}
	if len(data.Obj) == 0 {
		return models.UnknownEvent{RawData: json.RawMessage(line)}
	}
	var header struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(data.Obj, &header); err != nil {
		return malformed(err)
	}
	if (header.Type == models.EventItemUpdate || header.Type == models.EventItemDelta) && data.Identity == nil {
		return malformed(fmt.Errorf("%s requires item identity", header.Type))
	}
	switch header.Type {
	case models.EventItemUpdate:
		var event models.ItemUpdateEvent
		if err := json.Unmarshal(data.Obj, &event); err != nil {
			return malformed(err)
		}
		event.EventContext = data.EventContext
		return event
	case models.EventItemDelta:
		var event models.ItemDeltaEvent
		if err := json.Unmarshal(data.Obj, &event); err != nil {
			return malformed(err)
		}
		event.EventContext = data.EventContext
		return event
	case models.EventRunUpdate:
		var event models.RunUpdateEvent
		if err := json.Unmarshal(data.Obj, &event); err != nil {
			return malformed(err)
		}
		event.EventContext = data.EventContext
		return event
	case models.EventStop:
		var event models.StopEvent
		if err := json.Unmarshal(data.Obj, &event); err != nil {
			return malformed(err)
		}
		event.EventContext = data.EventContext
		return event
	case models.EventHeartbeat:
		return models.HeartbeatEvent{}
	default:
		return models.UnknownEvent{RawData: json.RawMessage(line)}
	}
}
func malformed(err error) models.ErrorEvent {
	return models.ErrorEvent{Error: fmt.Sprintf("malformed stream data: %v", err), IsRetryable: false}
}
