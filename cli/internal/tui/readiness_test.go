package tui

import (
	tea "charm.land/bubbletea/v2"
	"context"
	"errors"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"testing"
	"time"
)

func TestStreamStopWaitsForIdle(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	ch := make(chan models.StreamEvent)
	sid := "session"
	m.streamCh = ch
	m.chatSessionID = &sid
	m.isStreaming = true
	updated, cmd := m.handleStreamEvent(StreamEventMsg{Channel: ch, Event: models.StopEvent{}})
	m = updated.(Model)
	if !m.isStreaming || cmd == nil {
		t.Fatal("STOP released input before idle")
	}
	updated, cmd = m.handleStreamDone(StreamDoneMsg{Channel: ch})
	m = updated.(Model)
	if !m.isStreaming || cmd == nil {
		t.Fatal("delivery end released input before idle")
	}
	updated, cmd = m.Update(sessionReadyMsg{sessionID: sid, channel: ch, err: errors.New("offline")})
	m = updated.(Model)
	if !m.isStreaming || cmd == nil {
		t.Fatal("failed readiness released input")
	}
	updated, _ = m.Update(sessionReadyMsg{sessionID: sid, channel: ch})
	if updated.(Model).isStreaming {
		t.Fatal("confirmed idle did not release input")
	}
}

func TestOldCompletionCannotReleaseNewRequest(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	old := make(chan models.StreamEvent)
	newer := make(chan models.StreamEvent)
	m.streamCh = newer
	m.isStreaming = true
	updated, _ := m.Update(sessionReadyMsg{sessionID: "old", channel: old})
	m = updated.(Model)
	updated, _ = m.handleStreamDone(StreamDoneMsg{Channel: old})
	m = updated.(Model)
	updated, _ = m.handleStreamEvent(StreamEventMsg{Channel: old, Event: models.ErrorEvent{Error: "old"}})
	m = updated.(Model)
	if !m.isStreaming || m.streamCh != newer {
		t.Fatal("old completion changed new request")
	}
}

func TestFailedDraftSurvivesForRetry(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	ch := make(chan models.StreamEvent)
	m.streamCh = ch
	m.isStreaming = true
	m.submittedMessage = "retry me"
	updated, _ := m.handleStreamEvent(StreamEventMsg{Channel: ch, Event: models.ErrorEvent{Error: "offline"}})
	if updated.(Model).input.textInput.Value() != "retry me" {
		t.Fatal("lost failed draft")
	}
}

func TestBusyEnterKeepsDraft(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	m.isStreaming = true
	m.input.textInput.SetValue("next question")
	updated, cmd := m.handleKey(tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd != nil || updated.(Model).input.textInput.Value() != "next question" {
		t.Fatal("busy submit discarded draft")
	}
}

func TestBusyEnterSelectsPickerItem(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	m.isStreaming = true
	m.readinessUnconfirmed = true
	m.llmModels = []modelOption{{name: "selected-model", label: "Selected model"}}
	m.viewport.showPicker(pickerModel, []pickerItem{{id: "0", label: "Selected model"}})
	updated, _ := m.handleKey(tea.KeyPressMsg{Code: tea.KeyEnter})
	m = updated.(Model)
	if m.viewport.pickerActive || m.modelOverride == nil || *m.modelOverride.ModelVersion != "selected-model" {
		t.Fatal("readiness blocked model selection")
	}
	if !m.isStreaming {
		t.Fatal("picker selection released an unconfirmed turn")
	}
}

type stoppingClient struct {
	api.ClientAPI
	stopped chan int
}

func (c stoppingClient) StopChatSession(_ context.Context, _ string, streamID int) {
	c.stopped <- streamID
}

func TestStopDuringSettlementUsesAcknowledgedIdentity(t *testing.T) {
	client := stoppingClient{stopped: make(chan int, 1)}
	m := NewModel(config.DefaultConfig(), client)
	ch := make(chan models.StreamEvent)
	sid := "session"
	m.chatSessionID = &sid
	m.streamCh = ch
	m.isStreaming = true
	updated, _ := m.handleStreamEvent(StreamEventMsg{Channel: ch, Event: models.MessageIDEvent{ReservedAgentMessageID: 11}})
	m = updated.(Model)
	updated, _ = m.handleStreamDone(StreamDoneMsg{Channel: ch})
	m = updated.(Model)
	m, _ = m.cancelStream()
	if !m.isStreaming {
		t.Fatal("Stop released unsettled request")
	}
	select {
	case id := <-client.stopped:
		if id != 11 {
			t.Fatalf("wrong Stop id %d", id)
		}
	case <-time.After(time.Second):
		t.Fatal("Stop was lost after delivery ended")
	}
}

func TestUnsupportedReadinessStopsPollingWithoutReleasingInput(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	ch := make(chan models.StreamEvent)
	m.streamCh = ch
	m.isStreaming = true
	updated, cmd := m.Update(sessionReadyMsg{sessionID: "session", channel: ch, err: &api.OnyxAPIError{StatusCode: 404, Detail: "Not found"}})
	m = updated.(Model)
	if cmd != nil || !m.isStreaming || !m.readinessUnconfirmed {
		t.Fatal("unsupported endpoint must stop polling without declaring idle")
	}
}

func TestReopeningActiveSessionPreservesReadinessOwner(t *testing.T) {
	for _, settling := range []bool{false, true} {
		m := NewModel(config.DefaultConfig(), nil)
		ch := make(chan models.StreamEvent)
		sid := "session"
		parent := 11
		m.chatSessionID = &sid
		m.parentMessageID = &parent
		m.streamCh = ch
		m.isStreaming = true
		m.settling = settling
		m.viewport.addUserMessage("current question")
		updated, cmd := m.handleSessionResumed(SessionResumedMsg{Detail: &models.ChatSessionDetailResponse{
			ChatSessionID: sid,
			Messages:      []models.ChatMessageDetail{{MessageID: 1, MessageType: "assistant", Message: "earlier answer"}},
		}})
		m = updated.(Model)
		if cmd != nil || !m.isStreaming || m.streamCh != ch || m.parentMessageID != &parent {
			t.Fatal("reopening replaced the active stream or its parent")
		}
		if len(m.viewport.entries) != 1 || m.viewport.entries[0].content != "current question" {
			t.Fatal("reopening replaced live history with the earlier saved snapshot")
		}
		updated, _ = m.Update(sessionReadyMsg{sessionID: sid, channel: ch})
		if updated.(Model).isStreaming {
			t.Fatal("reopening detached the existing readiness callback")
		}
	}
}
