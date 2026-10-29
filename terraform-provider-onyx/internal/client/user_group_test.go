package client

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

// routedRequest is one call the routing test server saw.
type routedRequest struct {
	Method string
	Path   string
	Body   []byte
}

// withStatus makes a route answer with a status other than 200.
func withStatus(status int, body string) string {
	return fmt.Sprintf("%s%d %s", statusMarker, status, body)
}

const statusMarker = "status:"

// newRoutingTestServer answers each request from routes, keyed by
// "METHOD /path", so one test can shape a sequence of calls.
func newRoutingTestServer(t *testing.T, routes map[string]string) (*Client, *[]routedRequest) {
	t.Helper()
	seen := &[]routedRequest{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		*seen = append(*seen, routedRequest{Method: r.Method, Path: r.URL.RequestURI(), Body: body})
		response, ok := routes[r.Method+" "+r.URL.RequestURI()]
		if !ok {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.RequestURI())
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(`{"detail": "not routed"}`))
			return
		}
		status := http.StatusOK
		if rest, ok := strings.CutPrefix(response, statusMarker); ok {
			code, body, _ := strings.Cut(rest, " ")
			status, _ = strconv.Atoi(code)
			response = body
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(response))
	}))
	t.Cleanup(server.Close)
	return newFastRetryClient(server.URL), seen
}

const (
	listPath = "GET /manage/admin/user-group?include_default=true"
	getPath  = "GET /manage/admin/user-group/4"
	notFound = `{"error_code": "NOT_FOUND", "detail": "User group not found"}`
)

// groupObject renders one group carrying the given connector ids.
func groupObject(t *testing.T, ccPairIDs []int64, upToDate bool) string {
	t.Helper()
	pairs := make([]map[string]any, 0, len(ccPairIDs))
	for _, id := range ccPairIDs {
		pairs = append(pairs, map[string]any{"id": id, "name": "pair"})
	}
	body, err := json.Marshal(map[string]any{
		"id":                 4,
		"name":               "engineering",
		"users":              []map[string]any{{"id": "u-1", "email": "a@example.com"}},
		"manager_ids":        []string{"u-1"},
		"cc_pairs":           pairs,
		"document_sets":      []any{},
		"personas":           []map[string]any{{"id": 12, "name": "support"}},
		"is_up_to_date":      upToDate,
		"is_up_for_deletion": false,
		"is_default":         false,
		"incognito_enabled":  false,
	})
	if err != nil {
		t.Fatal(err)
	}
	return string(body)
}

// The roster write sends cc_pair_ids as null, which keeps the connector links
// server-side. Without it, a change that only names people would unshare the
// group's connectors. One call, no read first.
func TestSetUserGroupMembersKeepsConnectorLinks(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		"PATCH /manage/admin/user-group/4": groupObject(t, []int64{7, 9}, false),
	})

	if _, err := c.SetUserGroupMembers(context.Background(), 4, []string{"u-2", "u-3"}); err != nil {
		t.Fatal(err)
	}
	if len(*seen) != 1 {
		t.Fatalf("want one write and no read, got %d requests", len(*seen))
	}
	body := bodyAsMap(t, (*seen)[0].Body)
	pairs, present := body["cc_pair_ids"]
	if !present || pairs != nil {
		t.Errorf("cc_pair_ids must be sent as null, got %s", (*seen)[0].Body)
	}
	users, ok := body["user_ids"].([]any)
	if !ok || len(users) != 2 {
		t.Errorf("want the whole roster, got %v", body["user_ids"])
	}
}

// A nil roster clears the group rather than being dropped from the body.
func TestSetUserGroupMembersSendsAnEmptyRoster(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		"PATCH /manage/admin/user-group/4": groupObject(t, nil, false),
	})

	if _, err := c.SetUserGroupMembers(context.Background(), 4, nil); err != nil {
		t.Fatal(err)
	}
	body := bodyAsMap(t, (*seen)[0].Body)
	users, ok := body["user_ids"].([]any)
	if !ok {
		t.Fatalf("user_ids must be sent even when empty: %s", (*seen)[0].Body)
	}
	if len(users) != 0 {
		t.Errorf("want an empty roster, got %v", users)
	}
}

func TestSetUserGroupMembersReportsAMissingGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{
		"PATCH /manage/admin/user-group/4": withStatus(http.StatusNotFound, notFound),
	})
	_, err := c.SetUserGroupMembers(context.Background(), 4, []string{"u-1"})
	if !IsNotFound(err) {
		t.Fatalf("want a not-found error for a group that has gone, got %v", err)
	}
}

// Rename is a fixed route carrying the id in the body, not a route under it.
func TestRenameUserGroupUsesTheFixedRoute(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		"PATCH /manage/admin/user-group/rename": groupObject(t, nil, false),
	})
	if _, err := c.RenameUserGroup(context.Background(), 4, "platform"); err != nil {
		t.Fatal(err)
	}
	body := bodyAsMap(t, (*seen)[0].Body)
	if body["id"].(float64) != 4 || body["name"].(string) != "platform" {
		t.Errorf("want the id and the new name in the body, got %s", (*seen)[0].Body)
	}
}

// Without include_default the seeded Admin and Basic groups are invisible.
func TestListUserGroupsAsksForDefaults(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{listPath: `[]`})
	if _, err := c.ListUserGroups(context.Background()); err != nil {
		t.Fatal(err)
	}
	if (*seen)[0].Path != "/manage/admin/user-group?include_default=true" {
		t.Errorf("the listing must ask for default groups, got %q", (*seen)[0].Path)
	}
}

func TestLookupUserGroupReadsOneGroup(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{getPath: groupObject(t, []int64{7}, true)})
	group, found, err := c.LookupUserGroup(context.Background(), 4)
	if err != nil {
		t.Fatal(err)
	}
	if !found || group.ID != 4 || len(group.CCPairIDs()) != 1 {
		t.Errorf("unexpected group: %+v", group)
	}
	if len(*seen) != 1 {
		t.Errorf("want one get-by-id call, got %d requests", len(*seen))
	}
}

// A 404 is an absence, not a failure.
func TestLookupUserGroupReportsAMissingGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{getPath: withStatus(http.StatusNotFound, notFound)})
	group, found, err := c.LookupUserGroup(context.Background(), 4)
	if err != nil {
		t.Fatal(err)
	}
	if found || group != nil {
		t.Errorf("want not-found, got %v", group)
	}
}

func TestLookupUserGroupReturnsOtherErrors(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{
		getPath: withStatus(http.StatusForbidden, `{"detail": "forbidden"}`),
	})
	if _, _, err := c.LookupUserGroup(context.Background(), 4); err == nil {
		t.Fatal("want the 403 returned, got none")
	}
}

// A write on a syncing group answers 409 RESOURCE_SYNCING. A plain conflict
// is a different error.
func TestIsSyncing(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{
		"DELETE /manage/admin/user-group/4": withStatus(http.StatusConflict,
			`{"error_code": "RESOURCE_SYNCING", "detail": "Specified user group is currently syncing."}`),
		"DELETE /manage/admin/user-group/5": withStatus(http.StatusConflict,
			`{"error_code": "CONFLICT", "detail": "conflict"}`),
	})
	if err := c.DeleteUserGroup(context.Background(), 4); !IsSyncing(err) {
		t.Errorf("want IsSyncing for RESOURCE_SYNCING, got %v", err)
	}
	if err := c.DeleteUserGroup(context.Background(), 5); err == nil || IsSyncing(err) {
		t.Errorf("a plain conflict is not syncing, got %v", err)
	}
}

// Onyx has no bulk form: each manager change is its own call.
func TestSetGroupManagerCallsThePerUserRoute(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		"PUT /manage/admin/user-group/4/manager": `null`,
	})
	if err := c.SetGroupManager(context.Background(), 4, "u-1", true); err != nil {
		t.Fatal(err)
	}
	body := bodyAsMap(t, (*seen)[0].Body)
	if body["user_id"].(string) != "u-1" || body["is_manager"] != true {
		t.Errorf("want the user and the flag in the body, got %s", (*seen)[0].Body)
	}
}

// An empty grant set revokes; it must not be dropped from the body.
func TestSetUserGroupPermissionsSendsAnEmptyList(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		"PUT /manage/admin/user-group/4/permissions": `[]`,
	})
	if _, err := c.SetUserGroupPermissions(context.Background(), 4, nil); err != nil {
		t.Fatal(err)
	}
	body := bodyAsMap(t, (*seen)[0].Body)
	permissions, ok := body["permissions"].([]any)
	if !ok || len(permissions) != 0 {
		t.Errorf("want an empty permission list, got %s", (*seen)[0].Body)
	}
}

// The delete is asynchronous on a normal deployment and inline when Onyx runs
// without a vector database. Both end with the group answering 404.
func TestWaitForUserGroupDeletedAcceptsAnAlreadyGoneGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{getPath: withStatus(http.StatusNotFound, notFound)})
	if err := c.WaitForUserGroupDeleted(context.Background(), 4, 5*time.Second); err != nil {
		t.Fatal(err)
	}
}

// A group that has gone counts as settled, so waiting before a delete does not
// fail on one that has already finished.
func TestWaitForUserGroupSettledAcceptsAMissingGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{getPath: withStatus(http.StatusNotFound, notFound)})
	if err := c.WaitForUserGroupSettled(context.Background(), 4, 5*time.Second); err != nil {
		t.Fatal(err)
	}
}

func TestWaitForUserGroupSettledReturnsWhenUpToDate(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{getPath: groupObject(t, nil, true)})
	if err := c.WaitForUserGroupSettled(context.Background(), 4, 5*time.Second); err != nil {
		t.Fatal(err)
	}
}
