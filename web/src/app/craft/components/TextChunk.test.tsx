import { fireEvent, render, screen } from "@tests/setup/test-utils";
import TextChunk from "@/app/craft/components/TextChunk";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

jest.mock("@/hooks/useSmoothStreaming", () => ({
  useSmoothStreaming: () => ({ enabled: false }),
}));
jest.mock("@/hooks/useHighlightLanguages", () => ({
  useHighlightLanguages: () => null,
}));

beforeEach(() => {
  useBuildSessionStore.setState({
    sessions: new Map(),
    currentSessionId: null,
  });
  useBuildSessionStore.getState().createSession("message-session");
  useBuildSessionStore.getState().createSession("other-session");
  useBuildSessionStore.getState().setCurrentSession("other-session");
});

it.each([false, true])(
  "opens an output only on click, in the message's session (streaming=%s)",
  (isStreaming) => {
    render(
      <TextChunk
        sessionId="message-session"
        isStreaming={isStreaming}
        content="[Scenic Route](outputs/Scenic%20Route.pptx)"
      />
    );
    const state = () => useBuildSessionStore.getState();
    expect(state().sessions.get("message-session")?.outputPanelOpen).toBe(
      false
    );
    const link = screen.getByRole("link", { name: "Scenic Route" });
    expect(link).toHaveAttribute(
      "href",
      "/api/build/sessions/message-session/artifacts/outputs/Scenic%20Route.pptx"
    );
    fireEvent.click(link);
    expect(state().sessions.get("message-session")).toMatchObject({
      outputPanelOpen: true,
      activePanelTabId: "file:outputs/Scenic Route.pptx",
    });
    expect(state().sessions.get("other-session")?.outputPanelOpen).toBe(false);
  }
);

it.each([
  "outputs/../secret",
  "outputs/%2e%2e/secret",
  "outputs/%252e%252e/secret",
  "outputs/nested%2f..%2fsecret",
  "outputs/deck.pptx?session_id=other-session",
  "outputs/.env",
  "outputs/%00secret",
  "outputs%2f..%2fsecret",
  "javascript:alert%281%29",
  "data:text/html,evil",
])("renders an unsafe output link as inactive text: %s", (href) => {
  render(
    <TextChunk sessionId="message-session" content={`[Unsafe](${href})`} />
  );
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Unsafe"));
  expect(
    useBuildSessionStore.getState().sessions.get("message-session")
      ?.outputPanelOpen
  ).toBe(false);
});

it("preserves external links and never treats their path as a session output", () => {
  render(
    <TextChunk
      sessionId="message-session"
      content="[External](https://example.com/outputs/deck.pptx)"
    />
  );
  expect(screen.getByRole("link", { name: "External" })).toHaveAttribute(
    "href",
    "https://example.com/outputs/deck.pptx"
  );
  expect(screen.getByRole("link", { name: "External" })).toHaveAttribute(
    "rel",
    "noopener noreferrer"
  );
  expect(
    useBuildSessionStore.getState().sessions.get("message-session")
      ?.outputPanelOpen
  ).toBe(false);
});

it("does not interpret raw HTML as an output control", () => {
  const { container } = render(
    <TextChunk
      sessionId="message-session"
      content={
        '<img src="x" onerror="alert(1)"><a href="outputs/deck.pptx">Deck</a>'
      }
    />
  );
  expect(container.querySelector("img, a, script")).toBeNull();
});

it("keeps output links inactive when there is no message session", () => {
  render(<TextChunk sessionId={null} content="[Deck](outputs/deck.pptx)" />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByText("Deck")).toBeInTheDocument();
});
