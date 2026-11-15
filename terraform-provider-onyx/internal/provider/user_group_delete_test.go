package provider

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

const syncingResponse = `{"error_code": "RESOURCE_SYNCING", "detail": "Specified user group is currently syncing."}`

// userGroupDeleteServer answers GET with a settled group and each DELETE with
// the next entry of deletes (status codes), repeating the last one. It counts
// the DELETE calls.
func userGroupDeleteServer(t *testing.T, deletes []int) (*userGroupResource, *int) {
	t.Helper()
	group, err := json.Marshal(syncedGroup(4))
	if err != nil {
		t.Fatal(err)
	}
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method != http.MethodDelete {
			_, _ = w.Write(group)
			return
		}
		status := deletes[min(calls, len(deletes)-1)]
		calls++
		w.WriteHeader(status)
		switch status {
		case http.StatusConflict:
			_, _ = w.Write([]byte(syncingResponse))
		case http.StatusNotFound:
			_, _ = w.Write([]byte(`{"error_code": "NOT_FOUND", "detail": "User group not found"}`))
		default:
			_, _ = w.Write([]byte(`null`))
		}
	}))
	t.Cleanup(server.Close)
	return &userGroupResource{
		client: client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"}),
	}, &calls
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

// A 404 on delete means the group has gone, so the destroy is finished.
func TestDeleteUserGroupAcceptsAGroupThatHasGone(t *testing.T) {
	r, _ := userGroupDeleteServer(t, []int{http.StatusNotFound})

	alreadyGone, err := r.deleteUserGroup(context.Background(), 4, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if !alreadyGone {
		t.Error("a 404 means the group has gone and the destroy is done")
	}
}

// A group can start syncing again between the wait and the delete. Onyx
// answers 409 RESOURCE_SYNCING, and the provider waits and tries again.
func TestDeleteUserGroupRetriesWhileSyncing(t *testing.T) {
	r, calls := userGroupDeleteServer(t, []int{http.StatusConflict, http.StatusOK})

	alreadyGone, err := r.deleteUserGroup(context.Background(), 4, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if alreadyGone {
		t.Error("the second delete succeeded, so the group was not already gone")
	}
	if *calls != 2 {
		t.Errorf("want two delete calls, got %d", *calls)
	}
}

func TestDeleteUserGroupGivesUpAfterRepeatedSyncing(t *testing.T) {
	r, calls := userGroupDeleteServer(t, []int{http.StatusConflict})

	alreadyGone, err := r.deleteUserGroup(context.Background(), 4, 5*time.Second)
	if alreadyGone {
		t.Fatal("the group is still there, so the destroy must not report it gone")
	}
	if err == nil || !strings.Contains(err.Error(), "still syncing") {
		t.Errorf("want an error that says the group is still syncing, got %v", err)
	}
	if *calls != maxUserGroupDeleteAttempts {
		t.Errorf("want %d delete calls, got %d", maxUserGroupDeleteAttempts, *calls)
	}
}

// A scoped group manager may read the group but not its permissions. Read
// keeps the known permissions instead of failing.
func TestReadUserGroupKeepsPermissionsWhenForbidden(t *testing.T) {
	group, err := json.Marshal(syncedGroup(4))
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/permissions") {
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"error_code": "INSUFFICIENT_PERMISSIONS", "detail": "forbidden"}`))
			return
		}
		_, _ = w.Write(group)
	}))
	t.Cleanup(server.Close)
	r := &userGroupResource{
		client: client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"}),
	}

	known := types.SetValueMust(types.StringType, []attr.Value{types.StringValue("manage:connectors")})
	model := userGroupResourceModel{Permissions: known}
	var diags diag.Diagnostics
	if !r.readInto(context.Background(), 4, &model, &diags, func(context.Context) {}) {
		t.Fatal("the group exists, so it must stay in state")
	}
	if diags.HasError() {
		t.Fatalf("a forbidden permissions read must not fail Read: %v", diags)
	}
	if !model.Permissions.Equal(known) {
		t.Errorf("want the known permissions kept, got %v", model.Permissions)
	}
	if model.Name.ValueString() != "engineering" {
		t.Errorf("the rest of the group must still refresh, got name %q", model.Name.ValueString())
	}
}
