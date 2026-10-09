package client

import (
	"context"
	"net/http"
	"testing"
)

const embeddingProvidersJSON = `[
	{"provider_type": "openai", "api_key": "sk-****5678", "api_url": null, "api_version": null, "deployment_name": null},
	{"provider_type": "cohere", "api_key": "co-****9999", "api_url": null, "api_version": null, "deployment_name": null}
]`

func TestUpsertEmbeddingProvider(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"provider_type": "openai", "api_key": "sk-****5678"}`)
	req := CloudEmbeddingProvider{ProviderType: "openai", APIKey: strPtr("sk-real-key")}
	out, err := c.UpsertEmbeddingProvider(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPut || captured.Path != "/admin/embedding/embedding-provider" {
		t.Errorf("got %s %s, want PUT /admin/embedding/embedding-provider", captured.Method, captured.Path)
	}
	if out.ProviderType != "openai" {
		t.Errorf("unexpected response: %+v", out)
	}

	// Full-replace upsert: all fields must be present even when nil.
	body := bodyAsMap(t, captured.Body)
	for _, field := range []string{"provider_type", "api_key", "api_url", "api_version", "deployment_name"} {
		if _, present := body[field]; !present {
			t.Errorf("field %q missing from upsert body: %s", field, captured.Body)
		}
	}
	if body["api_key"] != "sk-real-key" {
		t.Errorf("api_key should be the raw value: %s", captured.Body)
	}
}

func TestGetEmbeddingProvider(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, embeddingProvidersJSON)
	out, err := c.GetEmbeddingProvider(context.Background(), "cohere")
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/admin/embedding/embedding-provider" {
		t.Errorf("got %s %s, want GET /admin/embedding/embedding-provider", captured.Method, captured.Path)
	}
	if out.APIKey == nil || *out.APIKey != "co-****9999" {
		t.Errorf("unexpected provider: %+v", out)
	}

	if _, err := c.GetEmbeddingProvider(context.Background(), "voyage"); !IsNotFound(err) {
		t.Errorf("missing provider_type should return a 404 APIError, got %v", err)
	}
}

func TestDeleteEmbeddingProvider(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.DeleteEmbeddingProvider(context.Background(), "openai"); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/admin/embedding/embedding-provider/openai" {
		t.Errorf("got %s %s, want DELETE /admin/embedding/embedding-provider/openai", captured.Method, captured.Path)
	}
}
