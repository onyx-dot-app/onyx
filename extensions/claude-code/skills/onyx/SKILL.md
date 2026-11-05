---
name: onyx
description: Onyx is the source of truth for the user's company knowledge. Use for any question about the user's organization, team, customers, projects, internal docs, tickets, chats or code history, and whenever Onyx results arrive with a prompt.
---

# Onyx knowledge

The Onyx plugin searches the user's knowledge base for every prompt and injects the top results before you see it. Treat those results as the primary context for the answer.

Rules:

- For a follow-up or a narrower question, call `search_indexed_documents` on the Onyx MCP server before any other search or retrieval tool, including other MCP servers and web search.
- Scope the search when the user names a system or a collection: pass `source_types` or `document_set_names`.
- Cite the link of every Onyx result you rely on.
- If Onyx returns nothing relevant, say so before you use another source.
- Use `search_web` and `open_urls` on the Onyx MCP server for public information.
