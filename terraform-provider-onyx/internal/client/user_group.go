package client

import (
	"context"
	"fmt"
	"net/http"
	"time"
)

// userGroupBasePath is the Enterprise Edition group router. The routes live in
// ee/onyx/main.py and simply do not exist on Community Edition, where every
// call here answers 404.
const userGroupBasePath = "/manage/admin/user-group"

// UserGroupMember is one member of a group, trimmed to what the provider reads.
// The API returns the full UserInfo.
type UserGroupMember struct {
	ID    string `json:"id"`
	Email string `json:"email"`
}

// UserGroupNamedRef is an object shared with a group. The provider only needs
// the id, but the name makes a diagnostic legible.
type UserGroupNamedRef struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

// UserGroup mirrors the UserGroup snapshot.
//
// The API's own `permissions` field is a per-action affordance map for the
// admin UI, not the group's permission grants. The grants live behind the
// separate permissions endpoint, so the field is deliberately not decoded here.
type UserGroup struct {
	ID               int64               `json:"id"`
	Name             string              `json:"name"`
	Users            []UserGroupMember   `json:"users"`
	ManagerIDs       []string            `json:"manager_ids"`
	CCPairs          []UserGroupNamedRef `json:"cc_pairs"`
	DocumentSets     []UserGroupNamedRef `json:"document_sets"`
	Personas         []UserGroupNamedRef `json:"personas"`
	IsUpToDate       bool                `json:"is_up_to_date"`
	IsUpForDeletion  bool                `json:"is_up_for_deletion"`
	IsDefault        bool                `json:"is_default"`
	IncognitoEnabled bool                `json:"incognito_enabled"`
}

// MemberIDs returns the member ids as the API reports them.
func (g *UserGroup) MemberIDs() []string {
	ids := make([]string, 0, len(g.Users))
	for _, user := range g.Users {
		ids = append(ids, user.ID)
	}
	return ids
}

// CCPairIDs returns the ids of the connector pairs shared with the group.
func (g *UserGroup) CCPairIDs() []int64 {
	ids := make([]int64, 0, len(g.CCPairs))
	for _, pair := range g.CCPairs {
		ids = append(ids, pair.ID)
	}
	return ids
}

// UserGroupCreate mirrors the backend's UserGroupCreate model.
type UserGroupCreate struct {
	Name      string   `json:"name"`
	UserIDs   []string `json:"user_ids"`
	CCPairIDs []int64  `json:"cc_pair_ids"`
}

// userGroupUpdate mirrors UserGroupUpdate. Both fields are a full replace, so
// the connector ids must always carry the current set — see SetUserGroupMembers.
type userGroupUpdate struct {
	UserIDs   []string `json:"user_ids"`
	CCPairIDs []int64  `json:"cc_pair_ids"`
}

type userGroupRename struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

type userGroupIncognitoUpdate struct {
	Enabled bool `json:"enabled"`
}

type setGroupManagerRequest struct {
	UserID    string `json:"user_id"`
	IsManager bool   `json:"is_manager"`
}

// addUsersToUserGroupRequest mirrors AddUsersToUserGroupRequest. It carries no
// connector ids: Onyx keeps the stored ones itself.
type addUsersToUserGroupRequest struct {
	UserIDs []string `json:"user_ids"`
}

type bulkSetPermissionsRequest struct {
	Permissions []string `json:"permissions"`
}

// CreateUserGroup creates a group. A duplicate name is refused rather than
// adopting the existing group.
//
// The new group is left syncing on any deployment with a vector database, so
// every following write must wait — see WaitForUserGroupSettled.
func (c *Client) CreateUserGroup(ctx context.Context, req UserGroupCreate) (*UserGroup, error) {
	if req.UserIDs == nil {
		req.UserIDs = []string{}
	}
	if req.CCPairIDs == nil {
		req.CCPairIDs = []int64{}
	}
	var group UserGroup
	if err := c.doJSON(ctx, http.MethodPost, userGroupBasePath, req, &group); err != nil {
		return nil, err
	}
	return &group, nil
}

// ListUserGroups returns every group the caller can see, the seeded default
// groups included. Without include_default the Admin and Basic groups are
// missing from the listing entirely.
func (c *Client) ListUserGroups(ctx context.Context) ([]UserGroup, error) {
	var groups []UserGroup
	path := userGroupBasePath + "?include_default=true"
	if err := c.doJSON(ctx, http.MethodGet, path, nil, &groups); err != nil {
		return nil, err
	}
	return groups, nil
}

// LookupUserGroup reads one group and reports whether it still exists.
//
// There is no get-by-id route, so this filters the listing.
func (c *Client) LookupUserGroup(ctx context.Context, id int64) (*UserGroup, bool, error) {
	groups, err := c.ListUserGroups(ctx)
	if err != nil {
		return nil, false, err
	}
	for i := range groups {
		if groups[i].ID == id {
			return &groups[i], true, nil
		}
	}
	return nil, false, nil
}

// SetUserGroupMembers makes the group roster match userIDs.
//
// Onyx's update endpoint replaces connector links along with members, and
// those links belong to onyx_cc_pair, so they have to survive a roster change.
// Which call does that best depends on the change:
//
// A roster that only gains members goes through the add-users endpoint. That
// one takes members alone, and Onyx preserves the connector links itself,
// reading and rewriting them inside the transaction that holds the membership
// lock. The read and the write are one step there, so a connector share made
// at the same moment cannot be overwritten by a list this client read a
// round-trip earlier.
//
// A roster that loses a member has no such endpoint and has to use the full
// replace, which means reading the connector ids here and sending them back.
// That read-modify-write spans two calls, so a connector share that lands in
// between is overwritten by the older list. Onyx offers nothing narrower —
// omitting the field is not "leave them alone", it is a validation error, and
// sending an empty list unshares every connector outright. The window is one
// round-trip and only opens for a removal.
func (c *Client) SetUserGroupMembers(ctx context.Context, id int64, userIDs []string) (*UserGroup, error) {
	current, found, err := c.LookupUserGroup(ctx, id)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, &APIError{
			StatusCode: http.StatusNotFound,
			Detail:     fmt.Sprintf("user group %d not found", id),
		}
	}

	if userIDs == nil {
		userIDs = []string{}
	}

	desired := make(map[string]bool, len(userIDs))
	for _, userID := range userIDs {
		desired[userID] = true
	}
	removes := false
	for _, memberID := range current.MemberIDs() {
		if !desired[memberID] {
			removes = true
			break
		}
	}

	// The whole roster goes out, not just the new names: Onyx works out which
	// of them are new and skips the rest.
	if !removes && len(userIDs) > 0 {
		var group UserGroup
		req := addUsersToUserGroupRequest{UserIDs: userIDs}
		path := fmt.Sprintf("%s/%d/add-users", userGroupBasePath, id)
		if err := c.doJSON(ctx, http.MethodPost, path, req, &group); err != nil {
			return nil, err
		}
		return &group, nil
	}

	req := userGroupUpdate{UserIDs: userIDs, CCPairIDs: current.CCPairIDs()}
	var group UserGroup
	path := fmt.Sprintf("%s/%d", userGroupBasePath, id)
	// Not replayed: a write that commits leaves the group syncing, so a replay
	// trips the gate the first attempt set and reports a failure for a change
	// that actually landed.
	if err := c.doJSON(nonReplayable(ctx), http.MethodPatch, path, req, &group); err != nil {
		return nil, err
	}
	return &group, nil
}

// RenameUserGroup renames a group. The route is a fixed path rather than one
// under the group id, and it carries the id in the body.
//
// Not replayed, for the same reason as the membership write: a committed
// rename leaves the group syncing, and the replay would be refused.
func (c *Client) RenameUserGroup(ctx context.Context, id int64, name string) (*UserGroup, error) {
	var group UserGroup
	req := userGroupRename{ID: id, Name: name}
	path := userGroupBasePath + "/rename"
	if err := c.doJSON(nonReplayable(ctx), http.MethodPatch, path, req, &group); err != nil {
		return nil, err
	}
	return &group, nil
}

// SetUserGroupIncognito turns incognito chat on or off for the group. Only
// meaningful while the deployment restricts incognito access to groups, but
// always storable.
func (c *Client) SetUserGroupIncognito(ctx context.Context, id int64, enabled bool) (*UserGroup, error) {
	var group UserGroup
	req := userGroupIncognitoUpdate{Enabled: enabled}
	path := fmt.Sprintf("%s/%d/incognito", userGroupBasePath, id)
	if err := c.doJSON(ctx, http.MethodPatch, path, req, &group); err != nil {
		return nil, err
	}
	return &group, nil
}

// SetGroupManager promotes or demotes one member. There is no bulk form, and
// the target must already be a member of the group.
func (c *Client) SetGroupManager(ctx context.Context, id int64, userID string, isManager bool) error {
	req := setGroupManagerRequest{UserID: userID, IsManager: isManager}
	path := fmt.Sprintf("%s/%d/manager", userGroupBasePath, id)
	return c.doJSON(ctx, http.MethodPut, path, req, nil)
}

// GetUserGroupPermissions returns the group's toggleable permission grants.
// Grants Onyx manages itself are excluded, which matches what the provider
// is able to write.
func (c *Client) GetUserGroupPermissions(ctx context.Context, id int64) ([]string, error) {
	var permissions []string
	path := fmt.Sprintf("%s/%d/permissions", userGroupBasePath, id)
	if err := c.doJSON(ctx, http.MethodGet, path, nil, &permissions); err != nil {
		return nil, err
	}
	return permissions, nil
}

// SetUserGroupPermissions replaces the group's permission grants and returns
// the stored set. Onyx refuses any permission it does not let a group toggle.
func (c *Client) SetUserGroupPermissions(ctx context.Context, id int64, permissions []string) ([]string, error) {
	if permissions == nil {
		permissions = []string{}
	}
	var enabled []string
	req := bulkSetPermissionsRequest{Permissions: permissions}
	path := fmt.Sprintf("%s/%d/permissions", userGroupBasePath, id)
	if err := c.doJSON(ctx, http.MethodPut, path, req, &enabled); err != nil {
		return nil, err
	}
	return enabled, nil
}

// DeleteUserGroup asks Onyx to delete a group. The row usually survives the
// call: the group is marked for deletion and a background sync removes it.
//
// Not replayed. A delete that commits but loses its response has already
// marked the group, so the replay meets the sync gate and reports a failure
// for a deletion that is under way.
func (c *Client) DeleteUserGroup(ctx context.Context, id int64) error {
	path := fmt.Sprintf("%s/%d", userGroupBasePath, id)
	return c.doJSON(nonReplayable(ctx), http.MethodDelete, path, nil, nil)
}

// WaitForUserGroupSettled waits until the group accepts gated writes again.
//
// Onyx refuses a membership change, a rename and a delete while a group is
// syncing, and a newly created group starts out syncing. Managers, incognito
// and permissions are not gated, so they need no wait. A group that has
// already gone counts as settled, so a caller waiting before a delete does not
// fail on a finished one.
func (c *Client) WaitForUserGroupSettled(ctx context.Context, id int64, timeout time.Duration) error {
	return Poll(ctx, timeout, "the user group to finish syncing",
		func(ctx context.Context) (bool, string, error) {
			group, found, err := c.LookupUserGroup(ctx, id)
			if err != nil {
				return false, "", err
			}
			if !found {
				return true, "", nil
			}
			return group.IsUpToDate, "a previous change is still syncing", nil
		})
}

// WaitForUserGroupDeleted waits until the group leaves the listing.
//
// The delete is asynchronous unless the deployment runs without a vector
// database, where the route removes the row inline; both finish here.
func (c *Client) WaitForUserGroupDeleted(ctx context.Context, id int64, timeout time.Duration) error {
	return Poll(ctx, timeout, "the user group to be deleted",
		func(ctx context.Context) (bool, string, error) {
			group, found, err := c.LookupUserGroup(ctx, id)
			if err != nil {
				return false, "", err
			}
			if !found {
				return true, "", nil
			}
			// The two cases need different answers from whoever reads the
			// timeout, so say which one it is rather than assuming the usual.
			if group.IsUpForDeletion {
				return false, "the group is marked for deletion and waiting on the background sync", nil
			}
			return false, "the group is still present and was never marked for deletion", nil
		})
}
