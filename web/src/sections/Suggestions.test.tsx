import { AnalyticsEvent } from "@/lib/analytics/utils";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import type { PersonSuggestions } from "@/lib/suggestedQuestions/types";
import Suggestions from "@/sections/Suggestions";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";

interface MockAgent {
  id: number;
  starter_messages: { message: string }[] | null;
}

let mockAgent: MockAgent | null = null;
let mockSuggestions: PersonSuggestions | undefined;
const mockMutate = jest.fn();
const mockTrack = jest.fn();
const mockMarkUsed = jest.fn((_id: string) => Promise.resolve());

jest.mock("@/lib/agents/hooks", () => ({
  useActiveAgent: () => mockAgent,
}));

jest.mock("@/lib/suggestedQuestions/hooks", () => ({
  useSuggestedQuestions: () => ({
    suggestions: mockSuggestions,
    mutate: mockMutate,
  }),
}));

jest.mock("@/lib/suggestedQuestions/svc", () => ({
  markSuggestedQuestionUsed: (id: string) => mockMarkUsed(id),
}));

jest.mock("@/lib/analytics/utils", () => ({
  ...jest.requireActual("@/lib/analytics/utils"),
  track: (...args: unknown[]) => mockTrack(...args),
}));

function suggestions(
  state: PersonSuggestions["state"],
  questions: PersonSuggestions["questions"] = []
): PersonSuggestions {
  return { state, questions };
}

beforeEach(() => {
  mockAgent = { id: DEFAULT_AGENT_ID, starter_messages: null };
  mockSuggestions = undefined;
  jest.clearAllMocks();
});

describe("an agent's own starter messages", () => {
  test("win over suggested questions", async () => {
    const onChat = jest.fn();
    mockAgent = { id: 7, starter_messages: [{ message: "What can you do?" }] };
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "Unused suggestion?", private: false },
    ]);
    render(<Suggestions onChat={onChat} />);

    await setupUser().click(screen.getByText("What can you do?"));

    expect(screen.queryByText("Unused suggestion?")).toBeNull();
    expect(onChat).toHaveBeenCalledWith({
      message: "What can you do?",
      mentions: [],
    });
    expect(mockTrack).not.toHaveBeenCalled();
    expect(mockMarkUsed).not.toHaveBeenCalled();
  });
});

describe("suggested questions on the default agent", () => {
  test("a click sends the question, marks it used and tracks it", async () => {
    const onChat = jest.fn();
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "What are our Q3 goals?", private: true },
      { id: "q2", message: "Who approves long trips?", private: false },
    ]);
    render(<Suggestions onChat={onChat} />);

    await setupUser().click(screen.getByText("Who approves long trips?"));

    expect(onChat).toHaveBeenCalledWith({
      message: "Who approves long trips?",
      mentions: [],
    });
    expect(mockMarkUsed).toHaveBeenCalledWith("q2");
    expect(mockTrack).toHaveBeenCalledWith(
      AnalyticsEvent.CLICKED_SUGGESTED_QUESTION,
      { position: 1, private: false }
    );
    // The clicked question leaves the list without a new request.
    expect(mockMutate).toHaveBeenCalledWith(expect.any(Function), {
      revalidate: false,
    });
    const update = mockMutate.mock.calls[0][0];
    expect(update(mockSuggestions)).toEqual({
      state: "ready",
      questions: [
        { id: "q1", message: "What are our Q3 goals?", private: true },
      ],
    });
  });

  test("a click that cannot be saved still sends, and is logged", async () => {
    const onChat = jest.fn();
    const error = new Error("network down");
    mockMarkUsed.mockReturnValueOnce(Promise.reject(error));
    const logged = jest.spyOn(console, "error").mockImplementation(() => {});
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "What are our Q3 goals?", private: true },
    ]);
    render(<Suggestions onChat={onChat} />);

    await setupUser().click(screen.getByText("What are our Q3 goals?"));

    expect(onChat).toHaveBeenCalled();
    await waitFor(() =>
      expect(logged).toHaveBeenCalledWith(
        "Could not mark the suggested question used:",
        error
      )
    );
    logged.mockRestore();
  });

  test("a click does nothing while sending is blocked", async () => {
    const onChat = jest.fn();
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "What are our Q3 goals?", private: true },
    ]);
    render(<Suggestions onChat={onChat} disabled />);

    await setupUser().click(screen.getByText("What are our Q3 goals?"));

    expect(onChat).not.toHaveBeenCalled();
    expect(mockMarkUsed).not.toHaveBeenCalled();
    expect(mockTrack).not.toHaveBeenCalled();
    expect(mockMutate).not.toHaveBeenCalled();
  });

  test.each(["preparing", "no_documents", "ready"] as const)(
    "shows nothing without questions (%s)",
    (state) => {
      mockSuggestions = suggestions(state);
      const { container } = render(<Suggestions onChat={jest.fn()} />);

      expect(container).toBeEmptyDOMElement();
    }
  );

  test("shows nothing while the first request is pending", () => {
    const { container } = render(<Suggestions onChat={jest.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  test("a custom agent without starter messages shows nothing", () => {
    mockAgent = { id: 7, starter_messages: [] };
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "Not for this agent?", private: false },
    ]);
    const { container } = render(<Suggestions onChat={jest.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });
});
