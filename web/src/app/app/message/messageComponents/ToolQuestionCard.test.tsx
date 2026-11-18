import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ToolQuestionCard from "@/app/app/message/messageComponents/ToolQuestionCard";
import { PENDING_QUESTION, useToolRequestUi } from "@/lib/chat/toolApprovals";
import {
  PacketType,
  type ToolQuestionRequest,
} from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { followChatStream } from "@/lib/chat/settleChatSession";
import { readChatSessionStatus } from "@/lib/chat/sessionReadiness";
import type { ChatStream } from "@/app/app/types";

jest.mock("@/lib/chat/settleChatSession", () => ({
  ...jest.requireActual("@/lib/chat/settleChatSession"),
  followChatStream: jest.fn(),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  fetchSettledChatSession: jest.fn(),
  readChatSessionStatus: jest.fn(),
  waitForChatResponseEnd: jest.fn(),
}));

const continuation: ChatStream = { stream_id: 900, response_ids: [82] };

const request: ToolQuestionRequest = {
  type: PacketType.TOOL_QUESTION_REQUEST,
  question_request_id: "question-1",
  tool_call_id: "call-1",
  questions: [
    {
      id: "scope",
      header: "Scope",
      question: "Which files should I change?",
      options: [
        { label: "All files (Recommended)", description: "Every file." },
        { label: "Docs", description: "Only the docs." },
      ],
    },
  ],
};

const threeQuestions: ToolQuestionRequest = {
  ...request,
  question_request_id: "question-2",
  questions: [
    request.questions[0]!,
    {
      id: "format",
      header: "Format",
      question: "How should the notes look?",
      options: [
        { label: "Bullets", description: "" },
        { label: "Prose", description: "" },
      ],
    },
    {
      id: "tone",
      header: "Tone",
      question: "Which tone fits?",
      options: [
        { label: "Formal", description: "" },
        { label: "Casual", description: "" },
      ],
    },
  ],
};

/** A waiting card as the trailing region renders it: an answer this client
 * sent decides its status. */
function Harness({ questions = request }: { questions?: ToolQuestionRequest }) {
  const status = useToolRequestUi((state) =>
    state.localAnswers.get(questions.question_request_id)
  );
  return (
    <ToolQuestionCard
      question={{
        turnIndex: 1,
        request: questions,
        status: status ?? PENDING_QUESTION,
      }}
    />
  );
}

function respond(status: number, body: unknown) {
  return jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

beforeEach(() => {
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  jest.mocked(followChatStream).mockReset();
  jest.mocked(readChatSessionStatus).mockReset();
});
afterEach(() => jest.restoreAllMocks());

test("the Other note is one of the choices and the answer follows the continuation", async () => {
  const fetchSpy = respond(200, {
    question_request_id: "question-1",
    continuation,
  });
  const user = setupUser();
  render(<Harness />);

  const submit = screen.getByRole("button", { name: "Submit" });
  expect(submit).toBeDisabled();
  // One question needs no pages.
  expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
  expect(screen.queryByText(/^Question \d of/)).toBeNull();
  // Options keep the model's order, recommended first.
  expect(
    screen.getAllByRole("radio").map((option) => option.textContent)
  ).toEqual(["All files (Recommended)Every file.", "DocsOnly the docs."]);

  const docs = screen.getByRole("radio", { name: /^Docs/ });
  const other = screen.getByRole("textbox", { name: "Other answer to Scope" });
  await user.click(docs);
  await user.type(other, "Docs and the README");
  // Typing in Other clears the option, and picking an option clears Other.
  expect(docs).toHaveAttribute("aria-checked", "false");
  await user.click(docs);
  expect(other).toHaveValue("");
  await user.type(other, "Docs and the README");
  await user.click(submit);

  await waitFor(() =>
    expect(followChatStream).toHaveBeenCalledWith(
      "session",
      continuation,
      expect.any(String)
    )
  );
  const [url, init] = fetchSpy.mock.calls[0]!;
  expect(url).toBe("/api/chat/question-requests/question-1/answers");
  expect(JSON.parse(String(init?.body))).toEqual({
    answers: [
      {
        question_id: "scope",
        option_label: null,
        user_note: "Docs and the README",
      },
    ],
  });
  expect(screen.getByRole("status")).toHaveTextContent("Answered");
  expect(screen.getByText("Scope: Docs and the README")).toBeInTheDocument();
});

test("a question that no longer waits shows so and reads the chat status", async () => {
  respond(409, { detail: "This question was already answered" });
  jest.mocked(readChatSessionStatus).mockResolvedValue({
    is_processing: true,
    current_stream: continuation,
    has_active_subagents: false,
    has_startable_input: false,
    latest_response_id: 82,
    approvals_version: "2",
  });
  const user = setupUser();
  render(<Harness />);

  await user.type(
    screen.getByRole("textbox", { name: "Other answer to Scope" }),
    "Only tests"
  );
  await user.click(screen.getByRole("button", { name: "Submit" }));

  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("No longer waiting")
  );
  expect(followChatStream).toHaveBeenCalledWith(
    "session",
    continuation,
    expect.any(String)
  );
});

test("the options are one tab stop that arrow keys and Space choose from", async () => {
  const user = setupUser();
  render(<Harness />);
  const [first, second] = screen.getAllByRole("radio");

  // Without a choice, the first option is the group's one tab stop.
  expect(first).toHaveAttribute("tabindex", "0");
  expect(second).toHaveAttribute("tabindex", "-1");
  await user.tab();
  expect(first).toHaveFocus();
  await user.keyboard(" ");
  expect(first).toHaveAttribute("aria-checked", "true");

  await user.keyboard("{ArrowDown}");
  expect(second).toHaveFocus();
  expect(second).toHaveAttribute("aria-checked", "true");
  expect(second).toHaveAttribute("tabindex", "0");
  expect(first).toHaveAttribute("tabindex", "-1");

  await user.keyboard("{ArrowDown}");
  expect(first).toHaveFocus();
  expect(first).toHaveAttribute("aria-checked", "true");

  await user.keyboard("{End}");
  expect(second).toHaveAttribute("aria-checked", "true");
  await user.keyboard("{Home}");
  await user.keyboard("{Enter}");
  expect(first).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();

  // Tab leaves the group for Other and then for Submit; only typing in
  // Other clears the option.
  await user.tab();
  expect(
    screen.getByRole("textbox", { name: "Other answer to Scope" })
  ).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "Submit" })).toHaveFocus();
  expect(first).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
});

test("each question has its own page, and the choices stay across pages", async () => {
  const fetchSpy = respond(200, {
    question_request_id: "question-2",
    continuation,
  });
  const user = setupUser();
  render(<Harness questions={threeQuestions} />);
  const back = screen.getByRole("button", { name: "Back" });

  expect(screen.getByText("Question 1 of 3")).toBeInTheDocument();
  expect(screen.getByText("Which files should I change?")).toBeInTheDocument();
  expect(screen.queryByText("How should the notes look?")).toBeNull();
  expect(back).toBeDisabled();
  await user.click(screen.getByRole("radio", { name: /^Docs/ }));

  // Next moves on without an answer; it does not submit.
  await user.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByText("Question 2 of 3")).toBeInTheDocument();
  expect(screen.getByText("How should the notes look?")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Format" })).toHaveFocus();
  expect(screen.queryByText("Which files should I change?")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Next" }));

  // The last page submits, but only once every question has an answer.
  expect(screen.getByText("Question 3 of 3")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  expect(
    screen.getByText("Answer questions 2 and 3 to submit.")
  ).toBeInTheDocument();
  // Each page change gives the focus to the new page.
  expect(screen.getByRole("group", { name: "Tone" })).toHaveFocus();
  expect(
    screen.getByRole("button", { name: "Submit" })
  ).toHaveAccessibleDescription("Answer questions 2 and 3 to submit.");
  await user.click(screen.getByRole("radio", { name: "Formal" }));
  expect(screen.getByText("Answer question 2 to submit.")).toBeInTheDocument();

  await user.click(back);
  await user.type(
    screen.getByRole("textbox", { name: "Other answer to Format" }),
    "A table"
  );
  await user.click(back);
  expect(back).toBeDisabled();
  expect(screen.getByRole("group", { name: "Scope" })).toHaveFocus();
  expect(screen.getByRole("radio", { name: /^Docs/ })).toHaveAttribute(
    "aria-checked",
    "true"
  );
  await user.click(screen.getByRole("button", { name: "Next" }));
  expect(
    screen.getByRole("textbox", { name: "Other answer to Format" })
  ).toHaveValue("A table");
  await user.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByRole("radio", { name: "Formal" })).toHaveAttribute(
    "aria-checked",
    "true"
  );
  expect(screen.queryByText(/Answer question/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Submit" }));

  await waitFor(() => expect(followChatStream).toHaveBeenCalled());
  const [, init] = fetchSpy.mock.calls[0]!;
  expect(JSON.parse(String(init?.body))).toEqual({
    answers: [
      { question_id: "scope", option_label: "Docs", user_note: null },
      { question_id: "format", option_label: null, user_note: "A table" },
      { question_id: "tone", option_label: "Formal", user_note: null },
    ],
  });
  // The record lists every answer.
  expect(screen.getByText("Scope: Docs")).toBeInTheDocument();
  expect(screen.getByText("Format: A table")).toBeInTheDocument();
  expect(screen.getByText("Tone: Formal")).toBeInTheDocument();
});
