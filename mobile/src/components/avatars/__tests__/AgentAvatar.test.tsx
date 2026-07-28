import { describe, expect, it, jest } from "@jest/globals";
import { render } from "@testing-library/react-native";

import { AgentAvatar } from "@/components/avatars/AgentAvatar";
import { DEFAULT_AGENT_ID, MinimalAgent } from "@/chat/agents";

// Avoid pulling the native expo-image module (the uploaded-image branch isn't exercised).
jest.mock("expo-image", () => ({ Image: () => null }));
// Break the MMKV chain pulled transitively via AgentImage → @/api/config → @/state/session.
jest.mock("@/state/storage", () => ({
  appStorage: { getString: () => null, set: () => {}, remove: () => {} },
  queryStorage: {},
  makeMmkvStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

function agent(
  overrides: Partial<MinimalAgent> & { id: number },
): MinimalAgent {
  return {
    name: "X",
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

describe("AgentAvatar", () => {
  it("renders an uppercased monogram for a lettered name", () => {
    const { getByText } = render(
      <AgentAvatar agent={agent({ id: 3, name: "zeta" })} />,
    );
    expect(getByText("Z")).toBeTruthy();
  });

  it("renders no letter for a non-ASCII-letter name (falls back to a glyph)", () => {
    const { queryByText } = render(
      <AgentAvatar agent={agent({ id: 4, name: "7 Eleven" })} />,
    );
    expect(queryByText("7")).toBeNull();
  });

  it("prefers a mapped icon over the monogram when icon_name is known", () => {
    const { queryByText } = render(
      <AgentAvatar
        agent={agent({ id: 5, name: "Pen Pal", icon_name: "Pen" })}
      />,
    );
    expect(queryByText("P")).toBeNull();
  });

  it("renders the default logo (no monogram) for the default agent", () => {
    const { queryByText } = render(
      <AgentAvatar
        agent={agent({ id: DEFAULT_AGENT_ID, name: "Assistant" })}
      />,
    );
    expect(queryByText("A")).toBeNull();
  });
});
