# `sections/agents/`

Agent UI shared by several agent pages (admin agents table, agents catalog,
agent viewer, etc.) that is not a component of its own: hooks such as the
filter bar, and menus. Agent components, `AgentCard` among them, live in
`@/lib/agents/components`.

---

## Components

### `AgentsFilters` (`useAgentsFilters`)

A hook that provides a shared filter bar for agent lists. Returns the
filtered agents and a renderable `filterBar` node containing "Created By"
and "Actions" filter popovers.

```tsx
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";
import { AgentCard } from "@/lib/agents/components";

function MyAgentsPage() {
  const { agents } = useAgents();
  const { filtered, filterBar } = useAgentsFilters(agents);
  const [viewedAgentId, setViewedAgentId] = useState<number | null>(null);

  return (
    <>
      <div className="flex flex-row gap-2">{filterBar}</div>
      {filtered.map((agent) => (
        <AgentCard
          key={agent.id}
          agent={agent}
          viewing={agent.id === viewedAgentId}
          onView={() => setViewedAgentId(agent.id)}
        />
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

| Filter     | Default label | What it filters                                                                    |
| ---------- | ------------- | ---------------------------------------------------------------------------------- |
| Created By | "Everyone"    | Agent creator (current user pinned to top)                                         |
| Actions    | "All Actions" | System tools (individually), MCP servers (grouped), OpenAPI actions (individually) |
