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

### `AgentsFilters` (`useAgentsFilters`)

A hook that provides a shared filter bar for agent lists. Returns the
filtered agents and a renderable `filterBar` node containing "Created By"
and "Actions" filter popovers.

```tsx
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";

function MyAgentsPage() {
  const { agents } = useAgents();
  const { filtered, filterBar } = useAgentsFilters(agents);

  return (
    <>
      <div className="flex flex-row gap-2">{filterBar}</div>
      {filtered.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </>
  );
}
```

**Parameters:**

- `agents: T[]` — an array of `MinimalPersonaSnapshot` (or any subtype like
  `Persona`). The generic preserves the input type in the returned `filtered`
  array.

**Returns:**

- `filtered: T[]` — the input agents with creator and action filters applied.
  When no filters are active, returns the original array.
- `filterBar: ReactNode` — the two filter popovers, ready to render.

**Filters included:**

| Filter | Default label | What it filters |
|---|---|---|
| Created By | "Everyone" | Agent creator (current user pinned to top) |
| Actions | "All Actions" | System tools (individually), MCP servers (grouped), OpenAPI actions (individually) |
