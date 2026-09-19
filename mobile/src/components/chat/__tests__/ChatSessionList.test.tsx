import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ChatSessionList } from "@/components/chat/ChatSessionList";
import type { ChatSessionSummary } from "@/api/chat/sessions";

// SidebarTab imports `router` from expo-router at module load; `jest.mock` is
// hoisted above the imports by babel-jest.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

function makeSession(
  overrides: Partial<ChatSessionSummary> & Pick<ChatSessionSummary, "id">,
): ChatSessionSummary {
  return {
    name: "Untitled",
    persona_id: 0,
    time_created: "2026-01-01T00:00:00Z",
    time_updated: "2026-01-01T00:00:00Z",
    shared_status: "private",
    current_alternate_model: null,
    current_temperature_override: null,
    ...overrides,
  };
}

describe("ChatSessionList", () => {
  it("renders session names and the 'New Chat' fallback for unnamed sessions", () => {
    render(
      <ChatSessionList
        sessions={[
          makeSession({ id: "a", name: "Q3 deck summary" }),
          makeSession({ id: "b", name: null }),
        ]}
        onSelect={jest.fn()}
      />,
    );

    expect(screen.getByText("Q3 deck summary")).toBeTruthy();
    expect(screen.getByText("New Chat")).toBeTruthy();
  });

  it("calls onSelect with the session id when a row is pressed", () => {
    const onSelect = jest.fn();
    render(
      <ChatSessionList
        sessions={[makeSession({ id: "abc", name: "Pick me" })]}
        onSelect={onSelect}
      />,
    );

    fireEvent.press(screen.getByText("Pick me"));
    expect(onSelect).toHaveBeenCalledWith("abc");
  });

  it("shows an empty state when there are no sessions", () => {
    render(<ChatSessionList sessions={[]} onSelect={jest.fn()} />);
    expect(
      screen.getByText(
        "Try sending a message! Your chat history will appear here.",
      ),
    ).toBeTruthy();
  });

  it("suppresses the empty state while loading", () => {
    render(<ChatSessionList sessions={[]} isLoading onSelect={jest.fn()} />);
    expect(
      screen.queryByText(
        "Try sending a message! Your chat history will appear here.",
      ),
    ).toBeNull();
  });

  it("offers a 'show older chats' affordance when more pages exist", () => {
    const onLoadMore = jest.fn();
    render(
      <ChatSessionList
        sessions={[makeSession({ id: "a", name: "Recent" })]}
        hasMore
        onSelect={jest.fn()}
        onLoadMore={onLoadMore}
      />,
    );

    fireEvent.press(screen.getByText("Show older chats"));
    expect(onLoadMore).toHaveBeenCalled();
  });
});
