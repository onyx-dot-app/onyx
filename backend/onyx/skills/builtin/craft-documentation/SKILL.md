---
name: craft-documentation
description: Answer questions about how Onyx and Onyx Craft work using the official documentation at docs.onyx.app. Use when the user asks what Craft can do, how a feature works, how to set up skills or apps, or how to deploy, configure, or administer Onyx.
---

# craft-documentation

Answer questions about Onyx and Onyx Craft from the official documentation at
https://docs.onyx.app. Use this whenever the user asks how Craft or Onyx works,
what a feature does, or how to set up, deploy, configure, or administer it,
rather than guessing from memory.

The docs are published with Mintlify, which serves clean, machine readable
copies of every page. Fetch those with the `webfetch` tool; there is no need to
render the site in a browser.

## Workflow

1. Fetch the index at https://docs.onyx.app/llms.txt. It lists every page as a
   Markdown link with a one line summary, so use it to find the right pages
   before reading anything else.
2. Pick the pages that match the question and fetch each one by appending `.md`
   to its URL, for example https://docs.onyx.app/overview/core_features/craft.md.
   The Craft topics live under `overview/core_features/`, `admins/managing_features/`,
   `deployment/`, and `security/architecture/`.
3. Answer from what you read, and cite each page by its title and URL.

## Notes

- Prefer targeted `.md` pages over the full corpus. The whole documentation is
  also available at https://docs.onyx.app/llms-full.txt, but it is large, so
  only reach for it when a question spans many pages.
- If the docs do not cover something, say so instead of guessing, and point the
  user to the closest relevant page.
