package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/parser"
)

// SendMessageStream starts streaming a chat message response.
// It reads NDJSON lines, parses them, and sends events on the returned channel.
// The goroutine stops when ctx is cancelled or the stream ends.
func (c *Client) SendMessageStream(
	ctx context.Context,
	message string,
	chatSessionID *string,
	agentID int,
	parentMessageID *int,
	fileDescriptors []models.FileDescriptorPayload,
) <-chan models.StreamEvent {
	ch := make(chan models.StreamEvent, 64)

	go func() {
		defer close(ch)

		payload := models.SendMessagePayload{
			Message:          message,
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

		req, err := c.newRequest(ctx, "POST", "/chat/send-chat-message", bytes.NewReader(body))
		if err != nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("request error: %v", err), IsRetryable: false}
			return
		}
		req.Header.Set("Content-Type", "application/json")

		resp, err := c.longHTTPClient.Do(req)
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
		if err := scanner.Err(); err != nil && ctx.Err() == nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("stream read error: %v", err), IsRetryable: true}
		}
	}()

	return ch
}
