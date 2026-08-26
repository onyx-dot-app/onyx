package client

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// routedRequest is one call the routing test server saw.
type routedRequest struct {
	Method string
	Path   string
	Body   []byte
}

// newRoutingTestServer answers each request from routes, keyed by
// "METHOD /path". SetUserGroupMembers reads before it writes, so a single
// canned response is not enough to shape its request.
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
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(response))
	}))
	t.Cleanup(server.Close)
	return newFastRetryClient(server.URL), seen
}

const listPath = "GET /manage/admin/user-group?include_default=true"

// groupObject renders one group carrying the given connector ids. The write
// routes answer with a single object; the listing wraps it in an array.
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
		"personas":           []any{},
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

func groupListing(t *testing.T, ccPairIDs []int64, upToDate bool) string {
	t.Helper()
	return "[" + groupObject(t, ccPairIDs, upToDate) + "]"
}

// A roster that only gains members goes through add-users, where Onyx keeps
// the connector links itself inside the transaction that holds the membership
// lock. That removes this client's read-modify-write, and with it the window
// where a connector share made at the same moment would be overwritten.
func TestSetUserGroupMembersAddsThroughTheAddUsersRoute(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		listPath: groupListing(t, []int64{7}, true),
		"POST /manage/admin/user-group/4/add-users": groupObject(t, []int64{7}, false),
	})

	// u-1 is already a member; u-2 is new. Nobody leaves.
	if _, err := c.SetUserGroupMembers(context.Background(), 4, []string{"u-1", "u-2"}); err != nil {
		t.Fatal(err)
	}
	if len(*seen) != 2 {
		t.Fatalf("want a read then a write, got %d requests", len(*seen))
	}
	if (*seen)[1].Path != "/manage/admin/user-group/4/add-users" {
		t.Errorf("an additive change must use add-users, got %s", (*seen)[1].Path)
	}

	body := bodyAsMap(t, (*seen)[1].Body)
	if _, present := body["cc_pair_ids"]; present {
		t.Error("add-users must not carry connector ids; Onyx preserves them itself")
	}
	users, ok := body["user_ids"].([]any)
	if !ok || len(users) != 2 {
		t.Errorf("want the whole roster, got %v", body["user_ids"])
	}
}

// A roster that loses a member has no additive route, so it falls back to the
// full replace — which replaces connector links along with members. Those links
// belong to onyx_cc_pair, so they have to be read and sent back. This is the
// regression guard for that: without the echo-back the pair is silently
// unshared from the group by a change that only mentioned people.
func TestSetUserGroupMembersRemovesThroughTheFullReplace(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		listPath:                           groupListing(t, []int64{7, 9}, true),
		"PATCH /manage/admin/user-group/4": groupObject(t, []int64{7, 9}, false),
	})

	// The listing holds u-1, and the new roster does not.
	if _, err := c.SetUserGroupMembers(context.Background(), 4, []string{"u-2"}); err != nil {
		t.Fatal(err)
	}
	if (*seen)[1].Method != http.MethodPatch {
		t.Fatalf("a removal must use the full replace, got %s %s", (*seen)[1].Method, (*seen)[1].Path)
	}
	body := bodyAsMap(t, (*seen)[1].Body)
	pairs, ok := body["cc_pair_ids"].([]any)
	if !ok || len(pairs) != 2 {
		t.Errorf("the full replace must still echo the connector ids, got %v", body["cc_pair_ids"])
	}
}

// A nil roster clears the group rather than being dropped from the body.
func TestSetUserGroupMembersSendsAnEmptyRoster(t *testing.T) {
	c, seen := newRoutingTestServer(t, map[string]string{
		listPath:                           groupListing(t, nil, true),
		"PATCH /manage/admin/user-group/4": groupObject(t, nil, false),
	})

	if _, err := c.SetUserGroupMembers(context.Background(), 4, nil); err != nil {
		t.Fatal(err)
	}
	body := bodyAsMap(t, (*seen)[1].Body)
	users, ok := body["user_ids"].([]any)
	if !ok {
		t.Fatalf("user_ids must be sent even when empty: %s", (*seen)[1].Body)
	}
	if len(users) != 0 {
		t.Errorf("want an empty roster, got %v", users)
	}
}

func TestSetUserGroupMembersReportsAMissingGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{listPath: `[]`})
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

// There is no get-by-id route, so a missing group is an absence from the
// listing rather than a 404.
func TestLookupUserGroupReportsAMissingGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{listPath: `[]`})
	group, found, err := c.LookupUserGroup(context.Background(), 4)
	if err != nil {
		t.Fatal(err)
	}
	if found || group != nil {
		t.Errorf("want not-found, got %v", group)
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
// without a vector database. Both end with the group out of the listing.
func TestWaitForUserGroupDeletedAcceptsAnAlreadyGoneGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{listPath: `[]`})
	if err := c.WaitForUserGroupDeleted(context.Background(), 4, 5*time.Second); err != nil {
		t.Fatal(err)
	}
}

// A group that has gone counts as settled, so waiting before a delete does not
// fail on one that has already finished.
func TestWaitForUserGroupSettledAcceptsAMissingGroup(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{listPath: `[]`})
	if err := c.WaitForUserGroupSettled(context.Background(), 4, 5*time.Second); err != nil {
		t.Fatal(err)
	}
}

func TestWaitForUserGroupSettledReturnsWhenUpToDate(t *testing.T) {
	c, _ := newRoutingTestServer(t, map[string]string{listPath: groupListing(t, nil, true)})
	if err := c.WaitForUserGroupSettled(context.Background(), 4, 5*time.Second); err != nil {
		t.Fatal(err)
	}
}
