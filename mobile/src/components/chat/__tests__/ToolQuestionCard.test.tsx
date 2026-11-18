import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import type { ReactElement } from "react";
import { AccessibilityInfo, Platform } from "react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render as renderView,
  waitFor,
} from "@testing-library/react-native";

import { postQuestionAnswers } from "@/api/chat/questions";
import { ApiError } from "@/api/errors";
import type { Message } from "@/chat/interfaces";
import {
  Packet,
  PacketType,
  StopReason,
  ToolQuestionRequest,
  ToolQuestionResolved,
} from "@/chat/streamingModels";
import {
  QuestionResolution,
  ToolQuestion,
  useToolQuestionUi,
} from "@/chat/toolQuestions";
import { MessageRow } from "@/components/chat/MessageRow";
import { ToolQuestionCard } from "@/components/chat/ToolQuestionCard";
import { recoverChatSession } from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/state/chatSessionStore";

jest.mock("@/api/chat/questions", () => ({ postQuestionAnswers: jest.fn() }));
jest.mock("@/hooks/useChatSessionController", () => ({
  recoverChatSession: jest.fn(),
  watchBackgroundAgents: jest.fn(),
}));
// These reach native modules that jest cannot load.
jest.mock("@/state/storage");
jest.mock("@/components/chat/StreamingMarkdown", () => ({}));

const postMock = postQuestionAnswers as unknown as Mock<
  typeof postQuestionAnswers
>;
const recoverMock = recoverChatSession as unknown as Mock<
  typeof recoverChatSession
>;

const request: ToolQuestionRequest = {
  type: "tool_question_request",
  question_request_id: "q1",
  tool_call_id: "c1",
  questions: [
    {
      id: "scope",
      header: "Scope",
      question: "Which scope?",
      options: [
        { label: "Small (Recommended)", description: "One file." },
        { label: "Large", description: "The whole app." },
      ],
    },
    {
      id: "tests",
      header: "Tests",
      question: "Add tests?",
      options: [
        { label: "Yes", description: "Unit tests." },
        { label: "No", description: "No tests." },
      ],
    },
  ],
};
const continuation = { stream_id: 40, response_ids: [2] };
const pausedStop: Packet = {
  placement: { turn_index: 0 },
  obj: { type: PacketType.STOP, stop_reason: StopReason.AWAITING_USER },
};

function render(element: ReactElement) {
  return renderView(
    <QueryClientProvider client={new QueryClient()}>
      {element}
    </QueryClientProvider>,
  );
}

function question(
  resolution: QuestionResolution | null = null,
  showsTypedAnswer = true,
) {
  const value: ToolQuestion = { turnIndex: 0, request, resolution };
  return (
    <ToolQuestionCard question={value} showsTypedAnswer={showsTypedAnswer} />
  );
}

function answerBoth(view: ReturnType<typeof render>) {
  fireEvent.press(view.getByText("Large"));
  fireEvent.press(view.getByLabelText("Next question"));
  fireEvent.press(view.getByText("Yes"));
}

function assistant(packets: Packet[]): Message {
  return {
    nodeId: 2,
    messageId: 2,
    parentNodeId: 1,
    type: "assistant",
    message: "",
    files: [],
    packets,
  };
}

function openPausedResponse() {
  useChatSessionStore.setState({ currentSessionId: "s", sessions: new Map() });
  useChatSessionStore
    .getState()
    .hydrateSession(
      "s",
      new Map([
        [
          2,
          assistant([
            { placement: { turn_index: 0 }, obj: request },
            pausedStop,
          ]),
        ],
      ]),
    );
}

describe("ToolQuestionCard", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useToolQuestionUi.setState({ localStatuses: new Map() });
    openPausedResponse();
  });

  it("shows one question per page with its options and an Other choice", () => {
    const view = render(question());

    expect(view.getByText("Questions for you")).toBeTruthy();
    expect(view.getByLabelText("Question 1 of 2")).toBeTruthy();
    expect(view.getByText("Which scope?")).toBeTruthy();
    expect(view.getByText("Small (Recommended)")).toBeTruthy();
    expect(view.getByText("The whole app.")).toBeTruthy();
    expect(view.getByText("Other")).toBeTruthy();
    expect(view.queryByText("Add tests?")).toBeNull();
    expect(
      view.getByLabelText("Back to the previous question").props
        .accessibilityState.disabled,
    ).toBe(true);
    expect(view.queryByLabelText("Submit your answers")).toBeNull();

    // Picking an option does not move to the next page.
    fireEvent.press(view.getByText("Large"));
    expect(view.getByText("Which scope?")).toBeTruthy();

    fireEvent.press(view.getByLabelText("Next question"));
    expect(view.getByLabelText("Question 2 of 2")).toBeTruthy();
    expect(view.getByText("Add tests?")).toBeTruthy();
    expect(view.queryByText("Which scope?")).toBeNull();
    expect(view.queryByLabelText("Next question")).toBeNull();
    expect(view.getByLabelText("Submit your answers")).toBeTruthy();
  });

  it("keeps choices and notes when the user moves between pages", () => {
    const view = render(question());

    fireEvent.press(view.getByText("Other"));
    fireEvent.changeText(view.getByLabelText("Your answer: Scope"), "Medium");
    fireEvent.press(view.getByLabelText("Next question"));
    fireEvent.press(view.getByText("No"));
    fireEvent.press(view.getByLabelText("Back to the previous question"));

    expect(view.getByLabelText("Your answer: Scope").props.value).toBe(
      "Medium",
    );
    fireEvent.press(view.getByLabelText("Next question"));
    expect(
      view.getByLabelText("No. No tests.").props.accessibilityState.checked,
    ).toBe(true);
  });

  it("announces the page on iOS when the user changes pages", () => {
    const original = Platform.OS;
    Platform.OS = "ios";
    const spy = jest
      .spyOn(AccessibilityInfo, "announceForAccessibility")
      .mockImplementation(() => {});
    try {
      const view = render(question());
      spy.mockClear();

      fireEvent.press(view.getByLabelText("Next question"));
      expect(spy).toHaveBeenLastCalledWith("Question 2 of 2");
      fireEvent.press(view.getByLabelText("Back to the previous question"));
      expect(spy).toHaveBeenLastCalledWith("Question 1 of 2");
    } finally {
      Platform.OS = original;
      spy.mockRestore();
    }
  });

  it("enables Submit only when every question has an answer", () => {
    const view = render(question());
    fireEvent.press(view.getByLabelText("Next question"));
    fireEvent.press(view.getByText("Yes"));

    const submit = () => view.getByLabelText("Submit your answers");
    expect(submit().props.accessibilityState.disabled).toBe(true);
    expect(view.getByText("Answer question 1 to submit.")).toBeTruthy();
    expect(submit().props.accessibilityHint).toBe(
      "Answer question 1 to submit.",
    );

    fireEvent.press(view.getByLabelText("Back to the previous question"));
    fireEvent.press(view.getByText("Small (Recommended)"));
    fireEvent.press(view.getByLabelText("Next question"));
    expect(submit().props.accessibilityState.disabled).toBe(false);
    expect(view.queryByText(/to submit\./)).toBeNull();
    expect(submit().props.accessibilityHint).toBeUndefined();
  });

  it("shows no page navigation for a single question", () => {
    const value: ToolQuestion = {
      turnIndex: 0,
      request: { ...request, questions: [request.questions[0]!] },
      resolution: null,
    };
    const view = render(<ToolQuestionCard question={value} showsTypedAnswer />);

    expect(view.getByText("Question for you")).toBeTruthy();
    expect(view.queryByText(/Question 1 of/)).toBeNull();
    expect(view.queryByLabelText("Back to the previous question")).toBeNull();
    expect(view.queryByLabelText("Next question")).toBeNull();
    fireEvent.press(view.getByText("Large"));
    expect(
      view.getByLabelText("Submit your answers").props.accessibilityState
        .disabled,
    ).toBe(false);
  });

  it("submits one choice per question and follows the continuation", async () => {
    postMock.mockResolvedValue({ question_request_id: "q1", continuation });
    const view = render(question());

    fireEvent.press(view.getByText("Small (Recommended)"));
    fireEvent.press(view.getByText("Large"));
    fireEvent.press(view.getByLabelText("Next question"));
    const submit = view.getByLabelText("Submit your answers");
    expect(submit.props.accessibilityState.disabled).toBe(true);
    fireEvent.press(view.getByText("Other"));
    // An empty note does not answer.
    expect(submit.props.accessibilityState.disabled).toBe(true);
    fireEvent.changeText(view.getByLabelText("Your answer: Tests"), " Later ");
    fireEvent.press(submit);

    const answers = [
      { question_id: "scope", option_label: "Large" },
      { question_id: "tests", user_note: "Later" },
    ];
    await waitFor(() => expect(recoverMock).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith("q1", { answers });
    expect(useToolQuestionUi.getState().localStatuses.get("q1")).toEqual({
      outcome: "answered",
      answered_via: "card",
      answers,
    });
    expect(recoverMock.mock.calls[0]?.slice(0, 2)).toEqual(["s", continuation]);
  });

  it("reads no inherited value for a question ID such as constructor", () => {
    const [first, second] = request.questions;
    const value: ToolQuestion = {
      turnIndex: 0,
      request: {
        ...request,
        questions: [first!, { ...second!, id: "constructor" }],
      },
      resolution: null,
    };
    const view = render(<ToolQuestionCard question={value} showsTypedAnswer />);

    fireEvent.press(view.getByText("Large"));
    fireEvent.press(view.getByLabelText("Next question"));
    expect(
      view.getByLabelText("Submit your answers").props.accessibilityState
        .disabled,
    ).toBe(true);
    fireEvent.press(view.getByText("Yes"));
    expect(
      view.getByLabelText("Submit your answers").props.accessibilityState
        .disabled,
    ).toBe(false);
  });

  it.each([404, 409])(
    "closes the question and reloads when the server answers %i",
    async (statusCode) => {
      postMock.mockRejectedValue(new ApiError({ status: statusCode }));
      const view = render(question());

      answerBoth(view);
      fireEvent.press(view.getByLabelText("Submit your answers"));

      await waitFor(() => expect(recoverMock).toHaveBeenCalled());
      expect(
        useToolQuestionUi.getState().localStatuses.get("q1")?.outcome,
      ).toBe("cancelled");
      expect(recoverMock.mock.calls[0]?.slice(0, 2)).toEqual(["s", null]);
      expect(useChatSessionStore.getState().sessions.get("s")?.chatState).toBe(
        "settling",
      );
      expect(view.queryByText(/Could not submit/)).toBeNull();
    },
  );

  // A message from the composer won the race; the server then refuses the card's answers.
  it("keeps an answer that already won when the server answers 409", async () => {
    let refuse: (reason: unknown) => void = () => {};
    postMock.mockReturnValue(
      new Promise((_resolve, reject) => {
        refuse = reject;
      }),
    );
    const typed: QuestionResolution = {
      outcome: "answered",
      answered_via: "message",
      message: "Small",
    };
    const view = render(question());

    answerBoth(view);
    fireEvent.press(view.getByLabelText("Submit your answers"));
    useToolQuestionUi.getState().recordStatuses(["q1"], typed);
    refuse(new ApiError({ status: 409 }));

    await waitFor(() => expect(recoverMock).toHaveBeenCalled());
    expect(useToolQuestionUi.getState().localStatuses.get("q1")).toBe(typed);
  });

  it("keeps the questions answerable after another failure", async () => {
    jest.spyOn(console, "warn").mockImplementation(() => {});
    postMock.mockRejectedValue(new ApiError({ status: 500 }));
    const view = render(question());

    answerBoth(view);
    fireEvent.press(view.getByLabelText("Submit your answers"));

    expect(
      await view.findByText("Could not submit your answers. Try again."),
    ).toBeTruthy();
    expect(useToolQuestionUi.getState().localStatuses.has("q1")).toBe(false);
    expect(recoverMock).not.toHaveBeenCalled();
    expect(
      view.getByLabelText("Submit your answers").props.accessibilityState
        .disabled,
    ).toBe(false);
  });

  it("shows the server's reason when it refuses the answers", async () => {
    jest.spyOn(console, "warn").mockImplementation(() => {});
    postMock.mockRejectedValue(
      new ApiError({ status: 400, detail: "This note is not allowed." }),
    );
    const view = render(question());

    answerBoth(view);
    fireEvent.press(view.getByLabelText("Submit your answers"));

    expect(await view.findByText("This note is not allowed.")).toBeTruthy();
    expect(recoverMock).not.toHaveBeenCalled();
  });

  it("leaves the continuation to a reader that already runs", async () => {
    useChatSessionStore
      .getState()
      .setAbortController("s", new AbortController());
    postMock.mockResolvedValue({ question_request_id: "q1", continuation });
    const view = render(question());

    answerBoth(view);
    fireEvent.press(view.getByLabelText("Submit your answers"));

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("s")?.queuedFollow,
      ).toEqual({ stream: continuation }),
    );
    expect(recoverMock).not.toHaveBeenCalled();
  });

  it("records the card's answers", () => {
    const view = render(
      question({
        outcome: "answered",
        answered_via: "card",
        answers: [
          { question_id: "scope", option_label: "Large" },
          { question_id: "tests", user_note: "Later" },
        ],
      }),
    );
    expect(view.getByText("Answered")).toBeTruthy();
    expect(view.getByText("Scope: Large")).toBeTruthy();
    expect(view.getByText("Tests: Later")).toBeTruthy();
    expect(view.queryByLabelText("Submit your answers")).toBeNull();
  });

  it("shows a typed answer as the user's message", () => {
    const view = render(
      question({
        outcome: "answered",
        answered_via: "message",
        message: "Keep it small",
      }),
    );
    expect(view.getByText("Answered in chat")).toBeTruthy();
    expect(view.getByText("Keep it small")).toBeTruthy();
  });

  it("records a cancelled question", () => {
    const view = render(question({ outcome: "cancelled" }));
    expect(view.getByText("No longer waiting")).toBeTruthy();
    expect(view.queryByText("Which scope?")).toBeNull();
  });
});

describe("MessageRow questions", () => {
  beforeEach(() => {
    useToolQuestionUi.setState({ localStatuses: new Map() });
  });

  const requestPacket: Packet = { placement: { turn_index: 0 }, obj: request };

  function resolved(
    id: string,
    resolution: Omit<ToolQuestionResolved, "type" | "question_request_id">,
  ): Packet {
    return {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_QUESTION_RESOLVED,
        question_request_id: id,
        ...resolution,
      },
    };
  }

  it("shows the waiting card and the wait in the header", () => {
    const view = render(
      <MessageRow node={assistant([requestPacket, pausedStop])} agent={null} />,
    );
    expect(view.getByTestId("tool-question-card")).toBeTruthy();
    expect(view.getByText("Waiting for your answer")).toBeTruthy();
  });

  it("shows the server outcome over the local answer", () => {
    useToolQuestionUi.setState({
      localStatuses: new Map([
        ["q1", { outcome: "answered", answered_via: "card", answers: [] }],
      ]),
    });
    const view = render(
      <MessageRow
        node={assistant([
          requestPacket,
          resolved("q1", { outcome: "cancelled" }),
        ])}
        agent={null}
      />,
    );
    expect(view.getByText("No longer waiting")).toBeTruthy();
  });

  // One typed message answers both questions that a turn asked at once.
  it("shows one typed answer once for the questions it answered", () => {
    const typed = {
      outcome: "answered",
      answered_via: "message",
      message: "Keep it small",
    } as const;
    const view = render(
      <MessageRow
        node={assistant([
          requestPacket,
          {
            placement: { turn_index: 0 },
            obj: { ...request, question_request_id: "q2", tool_call_id: "c2" },
          },
          resolved("q1", typed),
          resolved("q2", typed),
        ])}
        agent={null}
      />,
    );
    expect(view.getAllByText("Answered in chat")).toHaveLength(2);
    expect(view.getAllByText("Keep it small")).toHaveLength(1);
  });
});
