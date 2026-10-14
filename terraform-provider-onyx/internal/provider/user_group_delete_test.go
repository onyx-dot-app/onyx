package provider

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// userGroupDeleteServer answers the listing with the given groups and every
// DELETE with 404 — what Onyx does both for a group that has gone and for one
// that is still syncing.
func userGroupDeleteServer(t *testing.T, listed []map[string]any) *userGroupResource {
	t.Helper()
	body, err := json.Marshal(listed)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method == http.MethodDelete {
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(`{"error_code": "NOT_FOUND", "detail": "Specified user group is currently syncing."}`))
			return
		}
		_, _ = w.Write(body)
	}))
	t.Cleanup(server.Close)
	return &userGroupResource{
		client: client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"}),
	}
}

func syncedGroup(id int64) map[string]any {
	return map[string]any{
		"id":                 id,
		"name":               "engineering",
		"users":              []any{},
		"manager_ids":        []string{},
		"cc_pairs":           []any{},
		"document_sets":      []any{},
		"personas":           []any{},
		"is_up_to_date":      true,
		"is_up_for_deletion": false,
		"is_default":         false,
		"incognito_enabled":  false,
	}
}

// A group that really has gone answers 404 and leaves the listing, so the
// destroy is finished.
func TestDeleteUserGroupAcceptsAGroupThatHasGone(t *testing.T) {
	r := userGroupDeleteServer(t, []map[string]any{})

	alreadyGone, err := r.deleteUserGroup(context.Background(), 4, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if !alreadyGone {
		t.Error("a group missing from the listing has gone and the destroy is done")
	}
}

// A syncing group answers 404 as well, because the route funnels every
// ValueError into not-found. Trusting that would drop a live group out of
// state and leave the next apply failing on the name it still holds.
func TestDeleteUserGroupRefusesA404WhileTheGroupIsStillListed(t *testing.T) {
	r := userGroupDeleteServer(t, []map[string]any{syncedGroup(4)})

	alreadyGone, err := r.deleteUserGroup(context.Background(), 4, 5*time.Second)
	if alreadyGone {
		t.Fatal("the group is still listed, so the destroy must not report it gone")
	}
	if err == nil {
		t.Fatal("want an error naming what happened, got none")
	}
	if !strings.Contains(err.Error(), "still listed") {
		t.Errorf("the error should say the group is still there, got %v", err)
	}
}
