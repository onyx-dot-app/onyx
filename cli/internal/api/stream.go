package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/parser"
)

// SendMessageStream starts streaming a chat message response.
// It reads NDJSON lines, parses them, and sends events on the returned channel.
// Cancellation waits up to ten seconds for acknowledgement before closing delivery.
func (c *Client) SendMessageStream(
	ctx context.Context,
	message string,
	chatSessionID *string,
	agentID int,
	parentMessageID *int,
	fileDescriptors []models.FileDescriptorPayload,
	llmOverride *models.LLMOverride,
) <-chan models.StreamEvent {
	ch := make(chan models.StreamEvent, 64)

	go func() {
		defer close(ch)
		// Keep delivery alive until acknowledgement when cancellation races admission.
		streamCtx, cancel := context.WithCancel(context.WithoutCancel(ctx))
		defer cancel()
		done := make(chan struct{})
		cancellationDone := make(chan struct{})
		defer func() {
			close(done)
			// The one-shot CLI can exit as soon as its event channel closes.
			<-cancellationDone
		}()
		type identity struct {
			session string
			stream  int
		}
		acknowledged := make(chan identity, 1)
		stopAcknowledged := func(id identity) {
			stopCtx, stopCancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer stopCancel()
			c.StopChatSession(stopCtx, id.session, id.stream)
		}
		go func() {
			defer close(cancellationDone)
			select {
			case <-ctx.Done():
			case <-done:
				if ctx.Err() == nil {
					return
				}
			}
			timer := time.NewTimer(10 * time.Second)
			defer timer.Stop()
			select {
			case id := <-acknowledged:
				stopAcknowledged(id)
			case <-done:
				// Delivery may close with an acknowledged cancellation still queued.
				select {
				case id := <-acknowledged:
					stopAcknowledged(id)
				default:
				}
			case <-timer.C:
			}
			cancel()
		}()
		sessionID := ""
		if chatSessionID != nil {
			sessionID = *chatSessionID
		}

		payload := models.SendMessagePayload{
			Message:          message,
			LLMOverride:      llmOverride,
			ParentMessageID:  parentMessageID,
			FileDescriptors:  fileDescriptors,
			Origin:           "api",
			IncludeCitations: true,
			Stream:           true,
		}
		if payload.FileDescriptors == nil {
			payload.FileDescriptors = []models.FileDescriptorPayload{}
		}

		if chatSessionID != nil {
			payload.ChatSessionID = chatSessionID
		} else {
			payload.ChatSessionInfo = &models.ChatSessionCreationInfo{AgentID: agentID}
		}

		body, err := json.Marshal(payload)
		if err != nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("marshal error: %v", err), IsRetryable: false}
			return
		}

		req, err := c.newRequest(streamCtx, "POST", "/chat/send-chat-message", bytes.NewReader(body))
		if err != nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("request error: %v", err), IsRetryable: false}
			return
		}
		req.Header.Set("Content-Type", "application/json")

		resp, err := c.streamingHTTPClient.Do(req)
		if err != nil {
			if ctx.Err() != nil {
				return // cancelled
			}
			wrapped := wrapTimeoutError(err)
			if apiErr, ok := wrapped.(*OnyxAPIError); ok {
				ch <- models.ErrorEvent{
					Error:       apiErr.Error(),
					IsRetryable: true,
					StatusCode:  apiErr.StatusCode,
				}
			} else {
				ch <- models.ErrorEvent{Error: fmt.Sprintf("connection error: %v", err), IsRetryable: true}
			}
			return
		}
		defer func() { _ = resp.Body.Close() }()

		if err := checkResponse(resp); err != nil {
			apiErr, ok := err.(*OnyxAPIError)
			if ok {
				ch <- models.ErrorEvent{
					Error:       fmt.Sprintf("HTTP %d: %s", apiErr.StatusCode, apiErr.Detail),
					IsRetryable: apiErr.StatusCode >= 500,
					StatusCode:  apiErr.StatusCode,
				}
			} else {
				ch <- models.ErrorEvent{
					Error:       err.Error(),
					IsRetryable: false,
					StatusCode:  resp.StatusCode,
				}
			}
			return
		}

		scanner := bufio.NewScanner(resp.Body)
		scanner.Buffer(make([]byte, 0, 1024*1024), 1024*1024)
		for scanner.Scan() {
			event := parser.ParseStreamLine(scanner.Text())
			switch e := event.(type) {
			case models.SessionCreatedEvent:
				sessionID = e.ChatSessionID
			case models.MessageIDEvent:
				if sessionID != "" {
					select {
					case acknowledged <- identity{sessionID, e.ReservedAgentMessageID}:
					default:
					}
				}
			}
			if event != nil {
				select {
				case ch <- event:
				case <-ctx.Done():
					// Continue reading for acknowledgement; the cancellation worker is bounded.
				}
			}
		}
		if err := scanner.Err(); err != nil && ctx.Err() == nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("stream read error: %v", err), IsRetryable: true}
		}
	}()

	return ch
}
