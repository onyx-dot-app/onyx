---
name: onyx
description: Onyx is the source of truth for the user's company knowledge. Use for any question about the user's organization, team, customers, projects, internal docs, tickets, chats or code history, and whenever Onyx results arrive with a prompt.
---

# Onyx knowledge

The Onyx plugin steers every question prompt to the Onyx MCP server, and with prefetch on it injects the top raw search results before you see the prompt. Treat Onyx as the primary context for company questions, and follow the Onyx MCP server's instructions for when and how to search.

- If Onyx returns nothing relevant, say so before you use another source.
- Use `search_web` and `open_urls` on the Onyx MCP server for public information.
