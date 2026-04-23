# `sections/agents/`

Shared UI components for rendering and interacting with agents. Any component
that is used across multiple agent-related pages (admin agents table, explore
agents page, agent viewer modal, etc.) belongs here.

---

## Components

### `AgentCard`

A card component that displays a single agent with its avatar, name,
description, and quick actions (pin, share, edit, stats, try).

```tsx
import AgentCard from "@/sections/agents/AgentCard";

<AgentCard agent={agent} />
```

**Props:**

- `agent: MinimalPersonaSnapshot` — the agent to display.

---

### `AgentFilters` (`useAgentFilters`)

A hook that provides a shared filter bar for agent lists. Returns a
`matchesFilters` predicate and a renderable `filterBar` node containing
"Created By" and "Actions" filter popovers.

```tsx
import { useAgentFilters } from "@/sections/agents/AgentFilters";

function MyAgentsPage() {
  const { agents } = useAgents();
  const { matchesFilters, filterBar } = useAgentFilters(agents);

  const visible = agents.filter(matchesFilters);

  return (
    <>
      <div className="flex flex-row gap-2">{filterBar}</div>
      {visible.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </>
  );
}
```

**Parameters:**

- `agents` — any array of objects with `{ owner, tools }`. Works with
  `MinimalPersonaSnapshot`, `Persona`, `AgentRow`, or any type satisfying
  the `AgentLike` interface.

**Returns:**

- `matchesFilters(agent)` — a memoized predicate. Returns `true` when the
  agent matches all active filters. Safe for `useMemo` dependency arrays.
- `filterBar` — a React node containing the two filter popovers.

**Filters included:**

| Filter | Default label | What it filters |
|---|---|---|
| Created By | "Everyone" | Agent creator (current user pinned to top) |
| Actions | "All Actions" | System tools (individually), MCP servers (grouped), OpenAPI actions (individually) |
