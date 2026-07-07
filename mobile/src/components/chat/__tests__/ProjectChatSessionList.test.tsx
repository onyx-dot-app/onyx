import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ProjectChatSessionList } from "@/components/chat/ProjectChatSessionList";
import type { ChatSessionSummary } from "@/api/chat/sessions";

// Pulls in ChatSessionList (for UNNAMED_CHAT) → SidebarTab → expo-router.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));
// AgentAvatar → AgentImage → @/api/config → @/state/storage (MMKV/nitro); break the chain.
jest.mock("expo-image", () => ({ Image: () => null }));
jest.mock("@/state/storage", () => ({
  appStorage: { getString: () => null, set: () => {}, remove: () => {} },
  queryStorage: {},
  makeMmkvStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

function makeChat(
  id: string,
  name: string | null,
  timeUpdated: string,
): ChatSessionSummary {
  return {
    id,
    name,
    persona_id: 0,
    time_created: "2026-01-01T00:00:00Z",
    time_updated: timeUpdated,
    shared_status: "private",
    current_alternate_model: null,
    current_temperature_override: null,
  };
}

describe("ProjectChatSessionList", () => {
  it("renders chat names newest-first regardless of input order", () => {
    render(
      <ProjectChatSessionList
        chats={[
          makeChat("old", "Older chat", "2026-06-01T00:00:00Z"),
          makeChat("new", "Newer chat", "2026-06-10T00:00:00Z"),
        ]}
        onSelect={jest.fn()}
      />,
    );

    const names = screen
      .getAllByText(/chat$/)
      .map((node) => node.props.children as string);
    expect(names).toEqual(["Newer chat", "Older chat"]);
  });

  it("falls back to 'New Chat' for unnamed chats", () => {
    render(
      <ProjectChatSessionList
        chats={[makeChat("a", null, "2026-06-01T00:00:00Z")]}
        onSelect={jest.fn()}
      />,
    );
    expect(screen.getByText("New Chat")).toBeTruthy();
  });

  it("calls onSelect with the chat id when a row is pressed", () => {
    const onSelect = jest.fn();
    render(
      <ProjectChatSessionList
        chats={[makeChat("abc", "Tap me", "2026-06-01T00:00:00Z")]}
        onSelect={onSelect}
      />,
    );

    fireEvent.press(screen.getByText("Tap me"));
    expect(onSelect).toHaveBeenCalledWith("abc");
  });

  it("shows an empty state when the project has no chats", () => {
    render(<ProjectChatSessionList chats={[]} onSelect={jest.fn()} />);
    expect(screen.getByText("No chats yet.")).toBeTruthy();
  });
});
