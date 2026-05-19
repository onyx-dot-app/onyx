---
name: linear
description: Query and mutate Linear (issues, projects, teams) on the connected user's behalf via a light GraphQL wrapper.
---

# Linear

The current user has connected their Linear account. Call Linear as that user
with the bundled helper. **You do not handle authentication** — requests to
`https://api.linear.app/graphql` are authenticated automatically by the Onyx
egress proxy. Never ask for or set a token.

## Usage

    python _external_apps/<this-dir>/linear_api.py <command> [args]

Read commands auto-paginate and prune empty fields. `create-issue` and
`comment` are the only writes.

    # The connected user
    python linear_api.py me

    # Teams (need team ids to create issues)
    python linear_api.py teams

    # Issues, filtered
    python linear_api.py issues --assignee me --state "In Progress"
    python linear_api.py issues --team ENG --limit 50

    # One issue by id or by identifier
    python linear_api.py issue ENG-123

    # Full-text search
    python linear_api.py search "login bug" --limit 30

    # Projects
    python linear_api.py projects

    # Create an issue / comment (writes)
    python linear_api.py create-issue <team_id> "Title" --description "Body"
    python linear_api.py comment <issue_id> "Looking into this"

    # Any other GraphQL (raw escape hatch; pass user input as variables)
    python linear_api.py call 'query($id:String!){ issue(id:$id){ title } }' '{"id":"..."}'

Use `--raw` to skip empty-field pruning. `python linear_api.py <command> -h`
shows its flags.

## Output

JSON on stdout. List commands return `{"ok": true, "<key>": [...], "count": N,
"truncated": bool}` (`truncated` means more existed past `--limit`). Failures
return `{"ok": false, "errors": [...]}` and exit non-zero — surface the error
rather than retrying blindly.

## Notes

- `create-issue` needs a team id (from `teams`); `--assignee` takes a user id.
- Never print or ask for the access token; you do not have it and do not need
  it.
