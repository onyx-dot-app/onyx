package client

import (
	"context"
	"fmt"
	"net/http"
	"testing"
)

const customToolResponse = `{
	"id": 7,
	"name": "weather",
	"description": "looks up the weather",
	"definition": {"openapi": "3.0.0"},
	"display_name": "weather",
	"in_code_tool_id": null,
	"custom_headers": [{"key": "X-Api-Key", "value": "secret"}],
	"passthrough_auth": false,
	"mcp_server_id": null,
	"oauth_config_id": null,
	"enabled": true,
	"default_chat_enabled": false
}`

func TestCreateCustomToolSendsFullBody(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, customToolResponse)
	tool, err := c.CreateCustomTool(context.Background(), CustomToolWrite{
		Name:          "weather",
		Description:   "looks up the weather",
		Definition:    map[string]any{"openapi": "3.0.0"},
		CustomHeaders: []Header{{Key: "X-Api-Key", Value: "secret"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if tool.ID != 7 || tool.DisplayName != "weather" {
		t.Errorf("unexpected tool: %+v", tool)
	}
	if len(tool.CustomHeaders) != 1 || tool.CustomHeaders[0].Value != "secret" {
		t.Errorf("headers come back with their values: %+v", tool.CustomHeaders)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/tool/custom" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	for _, field := range []string{"name", "description", "definition", "custom_headers", "passthrough_auth", "oauth_config_id"} {
		if _, ok := body[field]; !ok {
			t.Errorf("%s must be present: the write is a full replace", field)
		}
	}
}

// A null custom_headers means "leave unchanged" on the server, so an action
// with no headers has to send an empty list or its old headers survive.
func TestCustomToolWriteSendsEmptyHeaderListNotNull(t *testing.T) {
	for _, tc := range []struct {
		name string
		call func(c *Client) error
	}{
		{"create", func(c *Client) error {
			_, err := c.CreateCustomTool(context.Background(), CustomToolWrite{Name: "weather"})
			return err
		}},
		{"update", func(c *Client) error {
			_, err := c.UpdateCustomTool(context.Background(), 7, CustomToolWrite{Name: "weather"})
			return err
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c, captured := newTestServer(t, http.StatusOK, customToolResponse)
			if err := tc.call(c); err != nil {
				t.Fatal(err)
			}
			headers, ok := bodyAsMap(t, captured.Body)["custom_headers"]
			if !ok {
				t.Fatal("custom_headers is missing")
			}
			if headers == nil {
				t.Fatalf("custom_headers must be [] and not null, or the stored headers survive: %s", captured.Body)
			}
			if list, isList := headers.([]any); !isList || len(list) != 0 {
				t.Errorf("custom_headers = %v, want an empty list", headers)
			}
		})
	}
}

func TestUpdateCustomToolUsesPut(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, customToolResponse)
	if _, err := c.UpdateCustomTool(context.Background(), 7, CustomToolWrite{Name: "weather"}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPut || captured.Path != "/admin/tool/custom/7" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}

func TestDeleteCustomTool(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.DeleteCustomTool(context.Background(), 7); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/admin/tool/custom/7" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}

func TestGetCustomToolReadsThroughTheOpenEndpoint(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, customToolResponse)
	tool, err := c.GetCustomTool(context.Background(), 7)
	if err != nil {
		t.Fatal(err)
	}
	if tool.ID != 7 {
		t.Errorf("id = %d, want 7", tool.ID)
	}
	if captured.Method != http.MethodGet || captured.Path != "/tool/7" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}

func TestValidateCustomToolDefinitionReturnsMethods(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK,
		`{"methods": [{"name": "getWeather", "raw_name": "getWeather", "summary": "", "path": "/w", "method": "GET"}]}`)
	methods, err := c.ValidateCustomToolDefinition(context.Background(), map[string]any{"openapi": "3.0.0"})
	if err != nil {
		t.Fatal(err)
	}
	if len(methods) != 1 || methods[0].Name != "getWeather" {
		t.Errorf("unexpected methods: %+v", methods)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/tool/custom/validate" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	if _, ok := bodyAsMap(t, captured.Body)["definition"]; !ok {
		t.Error("definition must be present")
	}
}

func TestCustomToolWritesDefaultChatAvailability(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		for _, method := range []string{http.MethodPost, http.MethodPut} {
			t.Run(fmt.Sprintf("%s/%t", method, enabled), func(t *testing.T) {
				c, captured := newTestServer(t, http.StatusOK, customToolResponse)
				req := CustomToolWrite{Name: "weather", DefaultChatEnabled: enabled}
				var err error
				if method == http.MethodPost {
					_, err = c.CreateCustomTool(context.Background(), req)
				} else {
					_, err = c.UpdateCustomTool(context.Background(), 7, req)
				}
				if err != nil {
					t.Fatal(err)
				}
				body := bodyAsMap(t, captured.Body)
				if body["default_chat_enabled"] != enabled {
					t.Fatalf("default_chat_enabled = %v, want %v", body["default_chat_enabled"], enabled)
				}
				if _, exists := body["enabled"]; exists {
					t.Fatal("must not send legacy global enabled")
				}
				if captured.Method != method {
					t.Fatalf("method = %s, want %s", captured.Method, method)
				}
			})
		}
	}
}
