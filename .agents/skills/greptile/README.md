# greptile skills

[Agent Skills](https://agentskills.io) for automated PR review workflows. Supports GitHub, GitLab, Perforce, and local Greptile CLI reviews. Requires `git` + `gh` CLI (GitHub), `glab` CLI (GitLab), `p4` CLI (Perforce), or the Greptile CLI for local reviews.

## Skills

| Skill | Description |
|-------|-------------|
| [`check-pr`](skills/check-pr/) | Check a PR/MR/CL for unresolved comments, failing checks, incomplete description. Fix and resolve. |
| [`cli-review`](skills/cli-review/) | Run a Greptile CLI review from the current checkout and summarize findings. |
| [`greploop`](skills/greploop/) | Loop: trigger Greptile review, fix comments, re-review — until 5/5 confidence and zero comments. |

`check-pr` and `greploop` auto-detect the platform (GitHub, GitLab, or Perforce) from the environment. `cli-review` runs against the current local git checkout with the Greptile CLI.

## Requirements

| Platform | CLI tool | Install |
|----------|----------|---------|
| GitHub | `gh` | [cli.github.com](https://cli.github.com) |
| GitLab | `glab` | [gitlab.com/gitlab-org/cli](https://gitlab.com/gitlab-org/cli) |
| Perforce | `p4` | [perforce.com/downloads](https://www.perforce.com/downloads/helix-command-line-client-p4) |
| Greptile | `greptile` | [greptile.com/cli](https://www.greptile.com/cli) |

Authenticate before use: `gh auth login`, `glab auth login`, configure `P4PORT`/`P4USER`/`P4CLIENT` for Perforce, or `greptile login`.

## Install

### Recommended: skills CLI

```bash
npx skills add greptileai/skills -g
```

This uses the [skills CLI](https://skills.sh) to install all three skills globally for your agent.

To install into a single project instead of globally, run this from the project root:

```bash
npx skills add greptileai/skills
```

### Alternative: git clone + symlinks

```bash
git clone https://github.com/greptileai/skills.git ~/.claude/skills/greptile
cd ~/.claude/skills
ln -sfn greptile/skills/check-pr check-pr
ln -sfn greptile/skills/cli-review cli-review
ln -sfn greptile/skills/greploop greploop
```

Claude Code discovers skills by looking for `SKILL.md` files at `~/.claude/skills/<skill-name>/SKILL.md`. Since this is a multi-skill repo, symlinks are needed to expose each sub-skill at the expected depth.

## Usage

Invoke by name in your agent (e.g. `/check-pr 123`, `/cli-review`, or `/greploop`). If no PR/MR/CL number is given, `check-pr` and `greploop` auto-detect the PR/MR for the current branch, or the pending changelist for Perforce.

For self-hosted GitLab instances whose hostname doesn't contain "gitlab", pass `--vcs gitlab` explicitly. For Perforce, pass `--vcs perforce` if auto-detection fails.

## Plugin

The Greptile plugin for Claude Code and Codex lives in [`plugins/greptile`](plugins/greptile/). It bundles the Greptile MCP server and CLI, with `login` and `review` skills:

```
/plugin marketplace add greptileai/skills
/plugin install greptile@greptile-plugin
```

```
codex plugin marketplace add greptileai/skills
codex plugin add greptile@greptile-plugin
```

See its [README](plugins/greptile/README.md) for setup and the MCP tools.

## License

MIT
