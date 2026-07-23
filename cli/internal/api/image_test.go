package api_test

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func TestGenerateImage_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if !strings.HasSuffix(r.URL.Path, "/image-generation/generate") {
			t.Errorf("path = %s, want .../image-generation/generate", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"images": [{"data_base64": "YWJj", "mime_type": "image/png", "revised_prompt": "a cat"}]
		}`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	resp, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.Images) != 1 {
		t.Fatalf("expected 1 image, got %d", len(resp.Images))
	}
	if resp.Images[0].DataBase64 != "YWJj" || resp.Images[0].MimeType != "image/png" {
		t.Errorf("unexpected image payload: %+v", resp.Images[0])
	}
}

func TestGenerateImage_KeepaliveWhitespacePrefix(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`    {
			"images": [{"data_base64": "YWJj", "mime_type": "image/png", "revised_prompt": "a cat"}]
		}`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	resp, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.Images) != 1 {
		t.Fatalf("expected 1 image, got %d", len(resp.Images))
	}
}

func TestGenerateImage_InBandErrorEnvelope(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`  {"error_code": "LLM_PROVIDER_ERROR", "detail": "Image generation failed."}`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	_, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	if err == nil {
		t.Fatal("expected error for in-band error envelope")
	}
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("want *OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 502 {
		t.Errorf("status = %d, want 502", apiErr.StatusCode)
	}
	if apiErr.Detail != "Image generation failed." {
		t.Errorf("detail = %q", apiErr.Detail)
	}
}

func TestGenerateImage_InBandNotFoundEnvelope(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"error_code": "NOT_FOUND", "detail": "no provider"}`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	_, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("want *OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 404 {
		t.Errorf("status = %d, want 404", apiErr.StatusCode)
	}
}

func TestGenerateImage_InBandTimeoutEnvelope(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`  {"error_code": "GATEWAY_TIMEOUT", "detail": "Image generation timed out."}`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	_, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("want *OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 504 {
		t.Errorf("status = %d, want 504", apiErr.StatusCode)
	}
}

func TestGenerateImage_EmptyBodyIsError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	_, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("want *OnyxAPIError for empty body, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 502 {
		t.Errorf("status = %d, want 502", apiErr.StatusCode)
	}
}

func TestGenerateImage_KeepaliveOnlyStreamIsError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`   `))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	_, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	if err == nil {
		t.Fatal("expected error for whitespace-only body")
	}
}

func TestGenerateImage_TruncatedStreamIsError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`  {"images": [`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	_, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	if err == nil {
		t.Fatal("expected error for truncated body")
	}
}

func TestGenerateImage_404(t *testing.T) {
	srv := testutil.StatusServer(404)
	defer srv.Close()

	client := testutil.NewClient(srv.URL + "/api")
	_, err := client.GenerateImage(t.Context(), models.ImageGenerationRequest{Prompt: "a cat"})
	if err == nil {
		t.Fatal("expected error for 404")
	}
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("want *OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 404 {
		t.Errorf("status = %d, want 404", apiErr.StatusCode)
	}
}
