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
	"strconv"
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
		ProtocolVersion:  2,
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
	return c.stream(ctx, sessionID, false, nil, func(requestCtx context.Context) (*http.Request, error) {
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

// ResumeChatStream replays the session's running response from cursor and
// then follows it, like SendMessageStream. A nil streamID follows whichever
// response runs. Events arrive in complete batches, each ending with a
// StreamCursorEvent, so a request from the last cursor repeats no event. A
// StreamUnavailableEvent reports that the server has nothing to serve at the
// cursor. Cancelling ctx stops streamID at once when it is known.
func (c *Client) ResumeChatStream(ctx context.Context, sessionID string, streamID *int, cursor int) <-chan models.StreamEvent {
	query := url.Values{"cursor": {strconv.Itoa(cursor)}, "protocol_version": {"2"}}
	if streamID != nil {
		query.Set("stream_id", strconv.Itoa(*streamID))
	}
	return c.stream(ctx, sessionID, true, streamID, func(requestCtx context.Context) (*http.Request, error) {
		return c.newRequest(requestCtx, "GET", "/chat/chat-session/"+url.PathEscape(sessionID)+"/resume-stream?"+query.Encode(), nil)
	})
}

// stream delivers the events of one streaming response. Cancelling ctx stops
// knownStream, or the response that the server reports. A resume response
// that is 404 delivers only a StreamUnavailableEvent, and a resume response
// delivers events only in complete batches.
func (c *Client) stream(
	ctx context.Context,
	sessionID string,
	resume bool,
	knownStream *int,
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
		if knownStream != nil {
			acknowledged <- identity{sessionID, *knownStream}
		}
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

		if resume && resp.StatusCode == http.StatusNotFound {
			ch <- models.StreamUnavailableEvent{}
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

		deliver := func(event models.StreamEvent) {
			switch event.(type) {
			case models.SessionCreatedEvent, models.MessageIDEvent:
				// The caller needs these IDs to settle and continue a cancelled turn.
				select {
				case ch <- event:
					return
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
		var batch []models.StreamEvent

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
			acknowledgedStream := 0
			switch e := event.(type) {
			case models.SessionCreatedEvent:
				sessionID = e.ChatSessionID
			case models.MessageIDEvent:
				acknowledgedStream = e.ReservedAgentMessageID
			case models.StreamCursorEvent:
				// A replay from a cursor has no message ID line.
				acknowledgedStream = e.StreamID
			}
			if acknowledgedStream != 0 && sessionID != "" {
				select {
				case acknowledged <- identity{sessionID, acknowledgedStream}:
				default:
				}
			}
			if event == nil {
				continue
			}
			if resume {
				// A batch that the stream cuts before its cursor replays again.
				if _, isCursor := event.(models.StreamCursorEvent); !isCursor {
					batch = append(batch, event)
					continue
				}
				for _, batched := range batch {
					deliver(batched)
				}
				clear(batch)
				batch = batch[:0]
			}
			deliver(event)
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
