---
name: github
description: Read repositories, issues, and pull requests, open new issues, and add comments in GitHub on the user's behalf via the GitHub CLI (gh).
---

# GitHub

Use the GitHub CLI (`gh`) to act as the connected user. **You are already
authenticated** — the egress proxy injects the user's GitHub token on the wire.
Never run `gh auth login`, `gh auth logout`, or `gh auth setup-git`; just run
commands.

{{ACTION_AVAILABILITY_SECTION}}

## Usage

### The connected user

```
gh api user
```

### Repositories

```
gh repo view OWNER/REPO
gh repo list [OWNER] [--limit N]
```

### Issues

```
gh issue list --repo OWNER/REPO [--state open|closed|all] [--limit N]
gh issue view NUMBER --repo OWNER/REPO [--comments]
```

### Pull requests

```
gh pr list --repo OWNER/REPO [--state open|closed|all] [--limit N]
gh pr view NUMBER --repo OWNER/REPO [--comments]
```

### Search

```
gh search repos "language:python stars:>500" [--limit N]
gh search issues "repo:owner/repo is:open label:bug" [--limit N]
gh search prs "repo:owner/repo is:open" [--limit N]
```

### Open an issue (write)

```
gh issue create --repo OWNER/REPO --title "Title" [--body "Details"]
```

### Comment on an issue or PR (write)

```
gh issue comment NUMBER --repo OWNER/REPO --body "Looking into this"
gh pr comment NUMBER --repo OWNER/REPO --body "Looking into this"
```

### Arbitrary API calls

`gh api` reaches any REST endpoint; `gh api graphql` runs a GraphQL query. Pass
user input as fields/variables, not by string-formatting into the path/query.

```
gh api repos/OWNER/REPO/releases --paginate
```

## Output

`gh` prints human-readable text by default. For compact, parseable output that
keeps your context small, prefer `--json` with an explicit field list (and
`--jq` to filter):

```
gh pr list --repo OWNER/REPO --json number,title,state --jq '.[] | {number,title}'
```

Use `--limit N` on list/search commands to cap results. A non-zero exit means
the command failed — surface the error rather than retrying blindly.

## Notes

- **HTTPS only.** SSH and `github.com` git remotes are unreachable from here, so
  `git clone`/`push` against GitHub and `gh repo clone` over SSH will fail. Stay
  on the API commands above (and `gh api`).
- **Scopes are fixed** by the admin (repo, read:org, read:user). An operation
  needing a scope you don't have returns `403 / Resource not accessible` — tell
  the user rather than retrying.
- A command that isn't pre-approved may pause for the user's approval; if a call
  is blocked or returns `401`, report it instead of looping.
