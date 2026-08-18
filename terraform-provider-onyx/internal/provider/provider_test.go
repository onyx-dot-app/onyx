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

// Acceptance tests need TF_ACC=1 plus ONYX_TF_ACC_SERVER_URL (a live
// deployment). Auth uses ONYX_TF_ACC_API_KEY when set; otherwise the harness
// registers/logs in an admin (first registered user becomes admin) and mints
// an admin API key, mirroring the backend integration-test managers.

var testAccProtoV6ProviderFactories = map[string]func() (tfprotov6.ProviderServer, error){
	"onyx": providerserver.NewProtocol6WithError(New("test")()),
}

var (
	bootstrapOnce   sync.Once
	bootstrapKey    string
	bootstrapKeyErr error
	// 0 means unresolved — real ids come from a sequence starting at 1.
	bootstrapAdminGroupID int64
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

// testAccAdminGroupID returns the seeded "Admin" group id, the one group that
// exists on any deployment. Must run after testAccPreCheck.
func testAccAdminGroupID(t *testing.T) int64 {
	t.Helper()
	if bootstrapAdminGroupID != 0 {
		return bootstrapAdminGroupID
	}
	if bootstrapKey == "" {
		t.Fatal("testAccAdminGroupID called before testAccPreCheck")
	}
	// Only reached when ONYX_TF_ACC_API_KEY short-circuited the bootstrap.
	base := strings.TrimRight(testAccServerURL(), "/")
	if p := strings.Trim(testAccAPIPrefix(), "/"); p != "" {
		base += "/" + p
	}
	id, err := findAdminGroupID(&http.Client{Timeout: 30 * time.Second}, base, nil, bootstrapKey)
	if err != nil {
		t.Fatalf("failed to resolve the Admin group id: %v", err)
	}
	bootstrapAdminGroupID = id
	return id
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

	// Register (idempotent — failures like already-exists are ignored;
	// login below is the real gate).
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

	// permissions come from group membership now — must join the seeded "Admin" group.
	// A `role` field silently yields a group-less key that 403s on every admin route.
	adminGroupID, err := findAdminGroupID(httpClient, base, sessionCookie, "")
	if err != nil {
		return "", err
	}
	bootstrapAdminGroupID = adminGroupID
	keyBody, _ := json.Marshal(map[string]any{
		"name":      "terraform-provider-acceptance-tests",
		"group_ids": []int64{adminGroupID},
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

// findAdminGroupID looks up the seeded "Admin" group — hidden from the default listing
// unless include_default=true. Auth is by cookie during bootstrap, by API key after.
func findAdminGroupID(httpClient *http.Client, base string, sessionCookie *http.Cookie, apiKey string) (int64, error) {
	req, err := http.NewRequest(http.MethodGet, base+"/manage/admin/user-group?include_default=true", nil)
	if err != nil {
		return 0, err
	}
	if sessionCookie != nil {
		req.AddCookie(sessionCookie)
	}
	if apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiKey)
	}

	resp, err := httpClient.Do(req)
	if err != nil {
		return 0, fmt.Errorf("user group listing request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 300 {
		return 0, fmt.Errorf("user group listing failed with HTTP %d", resp.StatusCode)
	}

	var groups []struct {
		ID   int64  `json:"id"`
		Name string `json:"name"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&groups); err != nil {
		return 0, err
	}
	for _, group := range groups {
		if group.Name == "Admin" {
			return group.ID, nil
		}
	}
	return 0, fmt.Errorf("no seeded \"Admin\" group found; has the seed_default_groups migration run?")
}
