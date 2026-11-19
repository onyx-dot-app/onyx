import englishMessages from "@/i18n/messages/en.json";
import { AnalyticsEvent } from "@/lib/analytics/utils";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import type { PersonSuggestions } from "@/lib/suggestedQuestions/types";
import Suggestions from "@/sections/Suggestions";
import { render, screen, setupUser } from "@tests/setup/test-utils";

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

const copy = englishMessages.chat.suggestedQuestions;

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
    const onSubmit = jest.fn();
    mockAgent = { id: 7, starter_messages: [{ message: "What can you do?" }] };
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "Unused suggestion?", private: false },
    ]);
    render(<Suggestions onSubmit={onSubmit} />);

    await setupUser().click(screen.getByText("What can you do?"));

    expect(screen.queryByText("Unused suggestion?")).toBeNull();
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ message: "What can you do?" })
    );
    expect(mockTrack).not.toHaveBeenCalled();
    expect(mockMarkUsed).not.toHaveBeenCalled();
  });
});

describe("suggested questions on the default agent", () => {
  test("a click sends the question, marks it used and tracks it", async () => {
    const onSubmit = jest.fn();
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "What are our Q3 goals?", private: true },
      { id: "q2", message: "Who approves long trips?", private: false },
    ]);
    render(<Suggestions onSubmit={onSubmit} />);

    await setupUser().click(screen.getByText("Who approves long trips?"));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Who approves long trips?" })
    );
    expect(mockMarkUsed).toHaveBeenCalledWith("q2");
    expect(mockTrack).toHaveBeenCalledWith(
      AnalyticsEvent.CLICKED_SUGGESTED_QUESTION,
      { position: 1, private: false }
    );
    // The clicked question leaves the list without a new request.
    expect(mockMutate).toHaveBeenCalledWith(expect.any(Function), {
      revalidate: false,
    });
  });

  test("shows one line while questions are being prepared", () => {
    mockSuggestions = suggestions("preparing");
    render(<Suggestions onSubmit={jest.fn()} />);

    expect(screen.getByText(copy.preparing.text)).toBeInTheDocument();
  });

  test("shows one line when the person has no documents yet", () => {
    mockSuggestions = suggestions("no_documents");
    render(<Suggestions onSubmit={jest.fn()} />);

    expect(screen.getByText(copy.noDocuments.text)).toBeInTheDocument();
  });

  test("shows nothing when ready with no questions", () => {
    mockSuggestions = suggestions("ready");
    const { container } = render(<Suggestions onSubmit={jest.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  test("a custom agent without starter messages shows nothing", () => {
    mockAgent = { id: 7, starter_messages: [] };
    mockSuggestions = suggestions("ready", [
      { id: "q1", message: "Not for this agent?", private: false },
    ]);
    const { container } = render(<Suggestions onSubmit={jest.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });
});
