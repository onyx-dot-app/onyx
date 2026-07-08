import { describe, expect, it } from "@jest/globals";

import {
  agentMatchesSearch,
  buildAgentRail,
  DEFAULT_AGENT_ID,
  MinimalAgent,
  resolveLiveAgent,
  resolvePinnedAgents,
  splitAgentsForGallery,
} from "@/chat/agents";

function agent(
  overrides: Partial<MinimalAgent> & { id: number },
): MinimalAgent {
  return {
    name: `Agent ${overrides.id}`,
    description: "",
    starter_messages: null,
    uploaded_image_id: null,
    icon_name: null,
    is_public: true,
    is_listed: true,
    is_featured: false,
    builtin_persona: false,
    display_priority: null,
    labels: [],
    ...overrides,
  };
}

const defaultAgent = agent({ id: DEFAULT_AGENT_ID, builtin_persona: true });

describe("resolvePinnedAgents", () => {
  it("returns [] when there are no agents", () => {
    expect(resolvePinnedAgents([], [1, 2])).toEqual([]);
  });

  it("resolves explicit pinned ids in order, dropping unknown ids", () => {
    const agents = [agent({ id: 1 }), agent({ id: 2 }), agent({ id: 3 })];
    expect(resolvePinnedAgents(agents, [3, 99, 1]).map((a) => a.id)).toEqual([
      3, 1,
    ]);
  });

  it("falls back to featured (excluding id 0) when pinned is null/undefined", () => {
    const agents = [
      // A featured DEFAULT agent must still be excluded from the fallback.
      agent({ id: DEFAULT_AGENT_ID, builtin_persona: true, is_featured: true }),
      agent({ id: 1, is_featured: true }),
      agent({ id: 2, is_featured: false }),
      agent({ id: 3, is_featured: true }),
    ];
    expect(resolvePinnedAgents(agents, null).map((a) => a.id)).toEqual([1, 3]);
    expect(resolvePinnedAgents(agents, undefined).map((a) => a.id)).toEqual([
      1, 3,
    ]);
  });

  it("treats an explicit empty array as empty (no featured fallback)", () => {
    const agents = [agent({ id: 1, is_featured: true })];
    expect(resolvePinnedAgents(agents, [])).toEqual([]);
  });
});

describe("resolveLiveAgent", () => {
  const agents = [
    defaultAgent,
    agent({ id: 1, is_featured: true }),
    agent({ id: 2 }),
  ];

  it("returns null when no agents are loaded", () => {
    expect(
      resolveLiveAgent({
        agents: [],
        pinnedAgents: [],
        disableDefaultAssistant: false,
        selectedAgentId: 1,
        sessionPersonaId: null,
      }),
    ).toBeNull();
  });

  it("an existing session's persona wins over everything", () => {
    expect(
      resolveLiveAgent({
        agents,
        pinnedAgents: [],
        disableDefaultAssistant: false,
        selectedAgentId: 2,
        sessionPersonaId: 1,
      })?.id,
    ).toBe(1);
  });

  it("uses an explicit selection when there is no session", () => {
    expect(
      resolveLiveAgent({
        agents,
        pinnedAgents: [],
        disableDefaultAssistant: false,
        selectedAgentId: 2,
        sessionPersonaId: null,
      })?.id,
    ).toBe(2);
  });

  it("defaults to the id-0 agent when enabled", () => {
    expect(
      resolveLiveAgent({
        agents,
        pinnedAgents: [agent({ id: 1 })],
        disableDefaultAssistant: false,
        selectedAgentId: null,
        sessionPersonaId: null,
      })?.id,
    ).toBe(DEFAULT_AGENT_ID);
  });

  it("skips id 0 and prefers a non-default pinned agent when the default is disabled", () => {
    expect(
      resolveLiveAgent({
        agents,
        pinnedAgents: [defaultAgent, agent({ id: 2 })],
        disableDefaultAssistant: true,
        selectedAgentId: null,
        sessionPersonaId: null,
      })?.id,
    ).toBe(2);
  });

  it("ignores an explicit default-agent (id 0) selection when the default is disabled", () => {
    expect(
      resolveLiveAgent({
        agents,
        pinnedAgents: [agent({ id: 2 })],
        disableDefaultAssistant: true,
        selectedAgentId: DEFAULT_AGENT_ID,
        sessionPersonaId: null,
      })?.id,
    ).toBe(2);
  });
});

describe("buildAgentRail", () => {
  const all = [
    defaultAgent,
    agent({ id: 1 }),
    agent({ id: 2 }),
    agent({ id: 5 }),
  ];

  it("excludes the default agent", () => {
    expect(
      buildAgentRail([defaultAgent, agent({ id: 1 })], all, null).map(
        (a) => a.id,
      ),
    ).toEqual([1]);
  });

  it("appends the current agent when it isn't already pinned", () => {
    expect(buildAgentRail([agent({ id: 1 })], all, 5).map((a) => a.id)).toEqual(
      [1, 5],
    );
  });

  it("does not duplicate the current agent when already pinned", () => {
    expect(buildAgentRail([agent({ id: 5 })], all, 5).map((a) => a.id)).toEqual(
      [5],
    );
  });

  it("never appends the default agent as current", () => {
    expect(
      buildAgentRail([agent({ id: 1 })], all, DEFAULT_AGENT_ID).map(
        (a) => a.id,
      ),
    ).toEqual([1]);
  });
});

describe("splitAgentsForGallery", () => {
  const agents = [
    defaultAgent, // builtin → excluded
    agent({ id: 1, name: "Writer", is_featured: true }),
    agent({ id: 4, name: "Coder", is_featured: true }),
    agent({ id: 2, name: "Analyst", is_featured: false }),
    agent({ id: 7, name: "Researcher", is_featured: false }),
  ];

  it("splits featured/all, excludes builtins, sorts each by descending id", () => {
    const { featured, all } = splitAgentsForGallery(agents, "");
    expect(featured.map((a) => a.id)).toEqual([4, 1]);
    expect(all.map((a) => a.id)).toEqual([7, 2]);
  });

  it("filters by search across name and labels", () => {
    const withLabel = agent({
      id: 9,
      name: "Support",
      labels: [{ id: 1, name: "Billing" }],
    });
    const result = splitAgentsForGallery([...agents, withLabel], "bill");
    expect(result.all.map((a) => a.id)).toEqual([9]);
    expect(result.featured).toEqual([]);
  });
});

describe("agentMatchesSearch", () => {
  it("matches empty query, name substring, and label substring (case-insensitive)", () => {
    const a = agent({
      id: 1,
      name: "Docs Bot",
      labels: [{ id: 1, name: "HR" }],
    });
    expect(agentMatchesSearch(a, "")).toBe(true);
    expect(agentMatchesSearch(a, "docs")).toBe(true);
    expect(agentMatchesSearch(a, "hr")).toBe(true);
    expect(agentMatchesSearch(a, "finance")).toBe(false);
  });
});
