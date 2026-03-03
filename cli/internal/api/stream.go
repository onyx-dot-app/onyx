package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/parser"
)

// StreamEventMsg wraps a StreamEvent for Bubble Tea.
type StreamEventMsg struct {
	Event models.StreamEvent
}

// StreamDoneMsg signals the stream has ended.
type StreamDoneMsg struct {
	Err error
}

// SendMessageStream starts streaming a chat message response.
// It reads NDJSON lines, parses them, and sends events on the returned channel.
// The goroutine stops when ctx is cancelled or the stream ends.
func (c *Client) SendMessageStream(
	ctx context.Context,
	message string,
	chatSessionID *string,
	personaID int,
	parentMessageID *int,
	fileDescriptors []models.FileDescriptorPayload,
) <-chan models.StreamEvent {
	ch := make(chan models.StreamEvent, 64)

	go func() {
		defer close(ch)

		payload := models.SendMessagePayload{
			Message:          message,
			ParentMessageID:  parentMessageID,
			FileDescriptors:  make([]map[string]interface{}, 0),
			Origin:           "api",
			IncludeCitations: true,
			Stream:           true,
		}

		if chatSessionID != nil {
			payload.ChatSessionID = chatSessionID
		} else {
			payload.ChatSessionInfo = &models.ChatSessionCreationInfo{PersonaID: personaID}
		}

		for _, fd := range fileDescriptors {
			payload.FileDescriptors = append(payload.FileDescriptors, map[string]interface{}{
				"id":   fd.ID,
				"type": string(fd.Type),
				"name": fd.Name,
			})
		}

		body, err := json.Marshal(payload)
		if err != nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("marshal error: %v", err), IsRetryable: false}
			return
		}

		req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/api/chat/send-chat-message", nil)
		if err != nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("request error: %v", err), IsRetryable: false}
			return
		}

		req.Body = io.NopCloser(bytes.NewReader(body))
		req.ContentLength = int64(len(body))
		req.Header.Set("Content-Type", "application/json")
		if c.apiKey != "" {
			bearer := "Bearer " + c.apiKey
			req.Header.Set("Authorization", bearer)
			req.Header.Set("X-Onyx-Authorization", bearer)
		}

		client := &http.Client{Timeout: 5 * time.Minute}
		resp, err := client.Do(req)
		if err != nil {
			if ctx.Err() != nil {
				return // cancelled
			}
			ch <- models.ErrorEvent{Error: fmt.Sprintf("connection error: %v", err), IsRetryable: true}
			return
		}
		defer resp.Body.Close()

		if resp.StatusCode != 200 {
			var respBody [4096]byte
			n, _ := resp.Body.Read(respBody[:])
			ch <- models.ErrorEvent{
				Error:       fmt.Sprintf("HTTP %d: %s", resp.StatusCode, string(respBody[:n])),
				IsRetryable: resp.StatusCode >= 500,
			}
			return
		}

		scanner := bufio.NewScanner(resp.Body)
		scanner.Buffer(make([]byte, 0, 1024*1024), 1024*1024)
		for scanner.Scan() {
			if ctx.Err() != nil {
				return
			}
			event := parser.ParseStreamLine(scanner.Text())
			if event != nil {
				select {
				case ch <- event:
				case <-ctx.Done():
					return
				}
			}
		}
	}()

	return ch
}

// WaitForStreamEvent returns a tea.Cmd that reads one event from the channel.
// On channel close, it returns StreamDoneMsg.
func WaitForStreamEvent(ch <-chan models.StreamEvent) tea.Cmd {
	return func() tea.Msg {
		event, ok := <-ch
		if !ok {
			return StreamDoneMsg{}
		}
		return StreamEventMsg{Event: event}
	}
}

