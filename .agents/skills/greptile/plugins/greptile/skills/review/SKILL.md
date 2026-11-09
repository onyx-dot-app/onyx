---
name: review
description: Review the current branch with Greptile
argument-hint: "[base branch] [what to focus on]"
metadata:
  internal: true
allowed-tools: Bash(node ${CLAUDE_PLUGIN_ROOT}/scripts/greptile.mjs:*) mcp__plugin_greptile_greptile__get_code_review mcp__plugin_greptile_greptile__list_code_reviews
---

Run a Greptile review on the current branch, against its base branch.

Build the command from `$ARGUMENTS`, if the user supplied any:

- A branch name they want to review against becomes `--branch '<BRANCH>'`,
  quoted the same way as the instructions below.
- Anything else they wrote is what they want the reviewer to focus on. Pass it
  as `--instructions '<their words>'` using **single** quotes, so the reviewer
  receives their exact text. If their text contains a `'`, replace each one
  with `'\''` and change nothing else. Never use double quotes: `$` and
  backticks are live inside them, so `$PATH` would silently disappear from the
  instructions and `$(...)` would stop the run at a permission prompt.

```
GREPTILE_NO_AUTO_INSTALL=1 GREPTILE_NO_UPDATE_CHECK=1 node "${CLAUDE_PLUGIN_ROOT}/scripts/greptile.mjs" review --agent
```

Outside Claude Code (Codex), replace `${CLAUDE_PLUGIN_ROOT}` with the plugin
root: the absolute path two folders above this `SKILL.md`.

Always pass `--agent`; it selects plain output intended for AI agents.

`GREPTILE_NO_AUTO_INSTALL=1` suppresses the Mermaid renderer download. When a
review summary carries a diagram, the CLI otherwise fetches a small binary
(`mmdr`) into `~/.cache/greptile/bin/` to rasterize it. That is worth doing in
a terminal a person is watching; it is not worth doing here. Claude Code runs
this command without a TTY, so the inline-image path is dead either way and the
diagram degrades to a link to an SVG file — while the download itself would
still stall a review the user is waiting on. The diagram's Mermaid source
reaches you in the review text regardless.

`GREPTILE_NO_UPDATE_CHECK=1` is belt-and-braces. The CLI infers how it was
installed from its own path, and versions before the plugin was recognised read
a copy running from inside this plugin as a standalone install — which would
name an installer that cannot update the plugin's copy. The notice is already
suppressed here because `--agent` is non-interactive, so this only matters if
the command is ever run without it, or the invocation is copied elsewhere.
Updates arrive with the plugin either way.

Give the Bash call a **600000 ms timeout**. A review commonly runs longer than
the two-minute default.

If the run reports that no one is signed in, it prints `not signed in. Set
GREPTILE_API_KEY or run 'greptile login --api-key'`. Prefer OAuth over an API
key: tell the user to run `/greptile:login` (in Codex, the `login` skill), and stop there rather than
starting a browser sign-in inside this command.

This dispatches a **headless** review: it reviews the working branch and does
not need an open pull request. The review is stored on the user's Greptile
account, so the `greptile` MCP tools in this plugin can read it back —
`list_code_reviews` and `get_code_review` return it with `source: "headless"`.

After the review completes, summarize the findings and offer to fix them. Use
`get_code_review` for the full body of any finding you need more detail on.
