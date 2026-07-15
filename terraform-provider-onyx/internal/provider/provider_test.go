package provider

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"
	"github.com/hashicorp/terraform-plugin-go/tfprotov6"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// Acceptance tests run against a live Onyx deployment and are gated twice:
// the standard TF_ACC=1 (enforced by resource.Test) plus
// ONYX_TF_ACC_SERVER_URL pointing at the deployment (e.g.
// "http://localhost:8080" for a direct backend, with ONYX_TF_ACC_API_PREFIX
// defaulting to "" accordingly).
//
// Authentication uses ONYX_TF_ACC_API_KEY when set; otherwise the harness
// bootstraps one: it registers/logs in an admin user (on a fresh deployment
// the first registered user becomes admin) and mints an admin API key,
// mirroring backend/tests/integration/common_utils/managers/{user,api_key}.py.

var testAccProtoV6ProviderFactories = map[string]func() (tfprotov6.ProviderServer, error){
	"onyx": providerserver.NewProtocol6WithError(New("test")()),
}

var (
	bootstrapOnce   sync.Once
	bootstrapKey    string
	bootstrapKeyErr error
)

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func testAccServerURL() string {
	return os.Getenv("ONYX_TF_ACC_SERVER_URL")
}

func testAccAPIPrefix() string {
	if v, ok := os.LookupEnv("ONYX_TF_ACC_API_PREFIX"); ok {
		return v
	}
	return ""
}

func testAccPreCheck(t *testing.T) {
	t.Helper()
	serverURL := testAccServerURL()
	if serverURL == "" {
		t.Skip("ONYX_TF_ACC_SERVER_URL is not set; set it (e.g. http://localhost:8080) to run acceptance tests")
	}

	bootstrapOnce.Do(func() {
		bootstrapKey, bootstrapKeyErr = bootstrapAPIKey(serverURL, testAccAPIPrefix())
	})
	if bootstrapKeyErr != nil {
		t.Fatalf("failed to bootstrap an admin API key: %v", bootstrapKeyErr)
	}

	// The provider under test runs in-process, so its env-var fallbacks read
	// the test process environment.
	t.Setenv("ONYX_SERVER_URL", serverURL)
	t.Setenv("ONYX_API_KEY", bootstrapKey)
	t.Setenv("ONYX_API_PREFIX", testAccAPIPrefix())
}

// testAccClient returns an API client for pre/post-condition checks.
func testAccClient(t *testing.T) *client.Client {
	t.Helper()
	if bootstrapKey == "" {
		t.Fatal("testAccClient called before testAccPreCheck")
	}
	return client.NewClient(testAccServerURL(), testAccAPIPrefix(), bootstrapKey)
}

func bootstrapAPIKey(serverURL, apiPrefix string) (string, error) {
	if key := os.Getenv("ONYX_TF_ACC_API_KEY"); key != "" {
		return key, nil
	}

	base := strings.TrimRight(serverURL, "/")
	if p := strings.Trim(apiPrefix, "/"); p != "" {
		base += "/" + p
	}
	email := envOr("ONYX_TF_ACC_ADMIN_EMAIL", "admin_user@example.com")
	password := envOr("ONYX_TF_ACC_ADMIN_PASSWORD", "TestPassword123!")
	cookieName := envOr("AUTH_COOKIE_NAME", "fastapiusersauth")
	httpClient := &http.Client{Timeout: 30 * time.Second}

	// Register the user; on a fresh deployment the first registered user is
	// auto-promoted to admin. Failures (e.g. the user already exists) are
	// ignored — login below is the real gate.
	registerBody, _ := json.Marshal(map[string]string{
		"email":    email,
		"username": email,
		"password": password,
	})
	if resp, err := httpClient.Post(base+"/auth/register", "application/json", bytes.NewReader(registerBody)); err == nil {
		_ = resp.Body.Close()
	}

	loginResp, err := httpClient.PostForm(base+"/auth/login", url.Values{
		"username": {email},
		"password": {password},
	})
	if err != nil {
		return "", fmt.Errorf("login request to %s failed: %w", base, err)
	}
	defer func() { _ = loginResp.Body.Close() }()
	if loginResp.StatusCode >= 300 {
		return "", fmt.Errorf("login as %s failed with HTTP %d (set ONYX_TF_ACC_ADMIN_EMAIL/ONYX_TF_ACC_ADMIN_PASSWORD or ONYX_TF_ACC_API_KEY)", email, loginResp.StatusCode)
	}

	var sessionCookie *http.Cookie
	for _, c := range loginResp.Cookies() {
		if c.Name == cookieName {
			sessionCookie = c
			break
		}
	}
	if sessionCookie == nil {
		return "", fmt.Errorf("login succeeded but no %q cookie was returned", cookieName)
	}

	keyBody, _ := json.Marshal(map[string]string{
		"name": "terraform-provider-acceptance-tests",
		"role": "admin",
	})
	keyReq, err := http.NewRequest(http.MethodPost, base+"/admin/api-key", bytes.NewReader(keyBody))
	if err != nil {
		return "", err
	}
	keyReq.Header.Set("Content-Type", "application/json")
	keyReq.AddCookie(sessionCookie)

	keyResp, err := httpClient.Do(keyReq)
	if err != nil {
		return "", fmt.Errorf("API key creation request failed: %w", err)
	}
	defer func() { _ = keyResp.Body.Close() }()
	if keyResp.StatusCode >= 300 {
		return "", fmt.Errorf("API key creation failed with HTTP %d — is %s an admin user?", keyResp.StatusCode, email)
	}

	var descriptor struct {
		APIKey *string `json:"api_key"`
	}
	if err := json.NewDecoder(keyResp.Body).Decode(&descriptor); err != nil {
		return "", err
	}
	if descriptor.APIKey == nil || *descriptor.APIKey == "" {
		return "", fmt.Errorf("API key creation response did not include the key material")
	}
	return *descriptor.APIKey, nil
}
