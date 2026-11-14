package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/parser"
)

var errStreamIdle = errors.New("chat stream idle timeout")

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
	sessionID := ""
	if chatSessionID != nil {
		sessionID = *chatSessionID
		payload.ChatSessionID = chatSessionID
	} else {
		payload.ChatSessionInfo = &models.ChatSessionCreationInfo{AgentID: agentID}
	}
	body, err := json.Marshal(payload)
	return c.stream(ctx, sessionID, false, func(requestCtx context.Context) (*http.Request, error) {
		if err != nil {
			return nil, fmt.Errorf("marshal: %w", err)
		}
		req, err := c.newRequest(requestCtx, "POST", "/chat/send-chat-message", bytes.NewReader(body))
		if err == nil {
			req.Header.Set("Content-Type", "application/json")
		}
		return req, err
	})
}

// ResumeChatStream replays the session's running response from its start and
// then follows it, like SendMessageStream. The channel closes without events
// when the session runs nothing.
func (c *Client) ResumeChatStream(ctx context.Context, sessionID string) <-chan models.StreamEvent {
	return c.stream(ctx, sessionID, true, func(requestCtx context.Context) (*http.Request, error) {
		return c.newRequest(requestCtx, "GET", "/chat/chat-session/"+url.PathEscape(sessionID)+"/resume-stream?cursor=0", nil)
	})
}

// stream delivers the events of one streaming response. Cancelling ctx stops
// the response once the server reports its IDs. notFoundIsEmpty ends a 404
// response without events.
func (c *Client) stream(
	ctx context.Context,
	sessionID string,
	notFoundIsEmpty bool,
	newRequest func(context.Context) (*http.Request, error),
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

		// A dead connection fails after streamIdleTimeout without data, however
		// long the turn itself runs.
		requestCtx, cancelRequest := context.WithCancelCause(streamCtx)
		defer cancelRequest(nil)
		idle := time.AfterFunc(c.streamIdleTimeout, func() { cancelRequest(errStreamIdle) })
		defer idle.Stop()
		idleError := models.ErrorEvent{
			Error:       fmt.Sprintf("no data from the server for %s", c.streamIdleTimeout),
			IsRetryable: true,
			StatusCode:  http.StatusRequestTimeout,
		}

		req, err := newRequest(requestCtx)
		if err != nil {
			ch <- models.ErrorEvent{Error: fmt.Sprintf("request error: %v", err), IsRetryable: false}
			return
		}

		// The idle timer keeps running until the scanner loop, so it also bounds
		// the read of an error body.
		resp, err := c.streamHTTPClient.Do(req)
		if err != nil {
			idle.Stop()
			if ctx.Err() != nil {
				return // cancelled
			}
			if errors.Is(context.Cause(requestCtx), errStreamIdle) {
				ch <- idleError
				return
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

		if notFoundIsEmpty && resp.StatusCode == http.StatusNotFound {
			return
		}
		if err := checkResponse(resp); err != nil {
			apiErr, ok := err.(*OnyxAPIError)
			if ok {
				ch <- models.ErrorEvent{
					Error:       fmt.Sprintf("HTTP %d: %s", apiErr.StatusCode, apiErr.Detail),
					IsRetryable: apiErr.StatusCode >= 500,
					StatusCode:  apiErr.StatusCode,
					ErrorCode:   apiErr.ErrorCode,
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
		for {
			// Only time spent waiting on the server counts toward the idle limit.
			idle.Reset(c.streamIdleTimeout)
			scanned := scanner.Scan()
			idle.Stop()
			if !scanned {
				break
			}
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
				switch event.(type) {
				case models.SessionCreatedEvent, models.MessageIDEvent:
					// The caller needs these IDs to settle and continue a cancelled turn.
					select {
					case ch <- event:
						continue
					default:
					}
					select {
					case ch <- event:
					case <-streamCtx.Done():
					}
				default:
					select {
					case ch <- event:
					case <-ctx.Done():
						// Continue reading for acknowledgement; the cancellation worker is bounded.
					}
				}
			}
		}
		if err := scanner.Err(); err != nil && ctx.Err() == nil {
			if errors.Is(context.Cause(requestCtx), errStreamIdle) {
				ch <- idleError
				return
			}
			ch <- models.ErrorEvent{Error: fmt.Sprintf("stream read error: %v", err), IsRetryable: true}
		}
	}()

	return ch
}
