# EE part to implement on Onyx's side — MCP server group access

The CE PR ships everything except the **group/user row writer**, which lives in
`ee/` (Onyx doesn't accept `ee/` contributions, so it's stripped from the PR).

## What CE already provides (in the PR)
- `mcp_server.is_public` column + migration.
- `MCPServer__User` / `MCPServer__UserGroup` association tables already existed.
- `db/mcp.py`:
  - `get_mcp_servers_accessible_to_user(user, db)` + `user_can_access_mcp_server(user, id, db)` —
    read path: public OR direct-user OR via user's groups; admin/system bypass.
  - `make_mcp_server_private(server_id, user_ids, group_ids, db)` — **CE stub** that raises
    `NotImplementedError` if any users/groups are passed (mirrors `make_doc_set_private`).
- API (`server/features/mcp/api.py`): the simple create/edit endpoints accept `is_public` +
  `groups` + `users`, validate curator rights via the existing
  `fetch_ee_implementation_or_noop("onyx.db.user_group", "validate_object_creation_for_user")`,
  set `is_public`, and call the **versioned** `make_mcp_server_private`. The user-facing
  `GET /mcp/servers` is filtered by access. Response exposes `is_public` + `groups`.
- Security: `upsert_persona` rejects MCP tools from servers the acting user can't access.
- Frontend: `IsPublicGroupSelector` on the create/edit form (self-gates on tier).

## The one EE function to add
`ee/onyx/db/mcp.py::make_mcp_server_private(server_id, user_ids, group_ids, db_session)` —
identical shape to `ee/onyx/db/document_set.py::make_doc_set_private`: clear existing
`MCPServer__User` + `MCPServer__UserGroup` rows for the server, then insert the requested ones.
Called with empty lists when a server is made public (so it clears grants).

```python
def make_mcp_server_private(server_id, user_ids, group_ids, db_session):
    db_session.query(MCPServer__User).filter(
        MCPServer__User.mcp_server_id == server_id
    ).delete(synchronize_session="fetch")
    db_session.query(MCPServer__UserGroup).filter(
        MCPServer__UserGroup.mcp_server_id == server_id
    ).delete(synchronize_session="fetch")
    for uid in user_ids or []:
        db_session.add(MCPServer__User(mcp_server_id=server_id, user_id=uid))
    for gid in group_ids or []:
        db_session.add(MCPServer__UserGroup(mcp_server_id=server_id, user_group_id=gid))
```

With that wired, the CE read path + API + UI light up: only members of the assigned groups
(or directly-granted users) can add the server's tools to their agents; servers with no
restriction stay public to everyone (backward-compatible default).
