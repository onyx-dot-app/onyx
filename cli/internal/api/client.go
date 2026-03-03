// Package api provides the HTTP client for communicating with the Onyx server.
package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// Client is the Onyx API client.
type Client struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client
}

// NewClient creates a new API client from config.
func NewClient(cfg config.OnyxCliConfig) *Client {
	return &Client{
		baseURL: strings.TrimRight(cfg.ServerURL, "/"),
		apiKey:  cfg.APIKey,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// UpdateConfig replaces the client's config.
func (c *Client) UpdateConfig(cfg config.OnyxCliConfig) {
	c.baseURL = strings.TrimRight(cfg.ServerURL, "/")
	c.apiKey = cfg.APIKey
}

func (c *Client) newRequest(method, path string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequest(method, c.baseURL+path, body)
	if err != nil {
		return nil, err
	}
	if c.apiKey != "" {
		bearer := "Bearer " + c.apiKey
		req.Header.Set("Authorization", bearer)
		req.Header.Set("X-Onyx-Authorization", bearer)
	}
	return req, nil
}

func (c *Client) doJSON(method, path string, reqBody interface{}, result interface{}) error {
	var body io.Reader
	if reqBody != nil {
		data, err := json.Marshal(reqBody)
		if err != nil {
			return err
		}
		body = bytes.NewReader(data)
	}

	req, err := c.newRequest(method, path, body)
	if err != nil {
		return err
	}
	if reqBody != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return &OnyxAPIError{StatusCode: resp.StatusCode, Detail: string(respBody)}
	}

	if result != nil {
		return json.NewDecoder(resp.Body).Decode(result)
	}
	return nil
}

// TestConnection checks if the server is reachable and credentials are valid.
func (c *Client) TestConnection() (bool, string) {
	// Step 1: Basic reachability
	req, err := c.newRequest("GET", "/", nil)
	if err != nil {
		return false, fmt.Sprintf("Cannot connect to %s: %v", c.baseURL, err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return false, fmt.Sprintf("Cannot connect to %s. Is the server running?", c.baseURL)
	}
	resp.Body.Close()

	serverHeader := strings.ToLower(resp.Header.Get("Server"))

	if resp.StatusCode == 403 {
		if strings.Contains(serverHeader, "awselb") || strings.Contains(serverHeader, "amazons3") {
			return false, "Blocked by AWS load balancer (HTTP 403 on all requests).\n  Your IP address may not be in the ALB's security group or WAF allowlist."
		}
		return false, "HTTP 403 on base URL — the server is blocking all traffic.\n  This is likely a firewall, WAF, or IP allowlist restriction."
	}

	// Step 2: Authenticated check
	req2, err := c.newRequest("GET", "/api/chat/get-user-chat-sessions", nil)
	if err != nil {
		return false, fmt.Sprintf("Server reachable but API error: %v", err)
	}

	client := &http.Client{Timeout: 120 * time.Second}
	resp2, err := client.Do(req2)
	if err != nil {
		return false, fmt.Sprintf("Server reachable but API error: %v", err)
	}
	defer resp2.Body.Close()

	if resp2.StatusCode == 200 {
		return true, "Connected and authenticated."
	}

	bodyBytes, _ := io.ReadAll(io.LimitReader(resp2.Body, 300))
	body := string(bodyBytes)
	isHTML := strings.HasPrefix(strings.TrimSpace(body), "<")
	respServer := strings.ToLower(resp2.Header.Get("Server"))

	if resp2.StatusCode == 401 || resp2.StatusCode == 403 {
		if isHTML || strings.Contains(respServer, "awselb") {
			return false, fmt.Sprintf("HTTP %d from a reverse proxy (not the Onyx backend).\n  Check your deployment's ingress / proxy configuration.", resp2.StatusCode)
		}
		if resp2.StatusCode == 401 {
			return false, fmt.Sprintf("Invalid API key or token.\n  %s", body)
		}
		return false, fmt.Sprintf("Access denied — check that the API key is valid.\n  %s", body)
	}

	detail := fmt.Sprintf("HTTP %d", resp2.StatusCode)
	if body != "" {
		detail += fmt.Sprintf("\n  Response: %s", body)
	}
	return false, detail
}

// ListAgents returns visible agents.
func (c *Client) ListAgents() ([]models.AgentSummary, error) {
	var raw []models.AgentSummary
	if err := c.doJSON("GET", "/api/persona", nil, &raw); err != nil {
		return nil, err
	}
	var result []models.AgentSummary
	for _, p := range raw {
		if p.IsVisible {
			result = append(result, p)
		}
	}
	return result, nil
}

// ListChatSessions returns recent chat sessions.
func (c *Client) ListChatSessions() ([]models.ChatSessionDetails, error) {
	var resp struct {
		Sessions []models.ChatSessionDetails `json:"sessions"`
	}
	if err := c.doJSON("GET", "/api/chat/get-user-chat-sessions", nil, &resp); err != nil {
		return nil, err
	}
	return resp.Sessions, nil
}

// GetChatSession returns full details for a session.
func (c *Client) GetChatSession(sessionID string) (*models.ChatSessionDetailResponse, error) {
	var resp models.ChatSessionDetailResponse
	if err := c.doJSON("GET", "/api/chat/get-chat-session/"+sessionID, nil, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// RenameChatSession renames a session. If name is empty, the backend auto-generates one.
func (c *Client) RenameChatSession(sessionID string, name *string) (string, error) {
	payload := map[string]interface{}{
		"chat_session_id": sessionID,
	}
	if name != nil {
		payload["name"] = *name
	}
	var resp struct {
		NewName string `json:"new_name"`
	}
	if err := c.doJSON("PUT", "/api/chat/rename-chat-session", payload, &resp); err != nil {
		return "", err
	}
	return resp.NewName, nil
}

// UploadFile uploads a file and returns a file descriptor.
func (c *Client) UploadFile(filePath string) (*models.FileDescriptorPayload, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)

	part, err := writer.CreateFormFile("files", filepath.Base(filePath))
	if err != nil {
		return nil, err
	}
	if _, err := io.Copy(part, file); err != nil {
		return nil, err
	}
	writer.Close()

	req, err := c.newRequest("POST", "/api/user/projects/file/upload", &buf)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return nil, &OnyxAPIError{StatusCode: resp.StatusCode, Detail: string(body)}
	}

	var snapshot models.CategorizedFilesSnapshot
	if err := json.NewDecoder(resp.Body).Decode(&snapshot); err != nil {
		return nil, err
	}

	if len(snapshot.UserFiles) == 0 {
		return nil, &OnyxAPIError{StatusCode: 400, Detail: "File upload returned no files"}
	}

	uf := snapshot.UserFiles[0]
	return &models.FileDescriptorPayload{
		ID:   uf.FileID,
		Type: uf.ChatFileType,
		Name: filepath.Base(filePath),
	}, nil
}

// StopChatSession sends a stop signal for a streaming session (best-effort).
func (c *Client) StopChatSession(sessionID string) {
	req, err := c.newRequest("POST", "/api/chat/stop-chat-session/"+sessionID, nil)
	if err != nil {
		return
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return
	}
	resp.Body.Close()
}
