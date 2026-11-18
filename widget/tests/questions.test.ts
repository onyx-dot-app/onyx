import { afterEach, describe, expect, it, mock } from "bun:test";
import { nothing } from "lit";
import {
  ApiError,
  ApiService,
  type ResumeEnd,
} from "../src/services/api-service";
import {
  APPROVAL_PENDING_ERROR_CODE,
  type ApprovalEntry,
} from "../src/services/approvals";
import {
  type QuestionCardView,
  renderQuestionCard,
} from "../src/services/question-card";
import {
  draftAnswers,
  findPendingWait,
  type QuestionDraft,
  type QuestionEntry,
  questionRecords,
  type QuestionResolution,
  questionResolution,
} from "../src/services/questions";
import { processPacket } from "../src/services/stream-parser";
import type {
  ChatSessionDetail,
  Packet,
  StreamCursor,
  ToolApprovalRequest,
  ToolQuestionAnswer,
  ToolQuestionRequest,
} from "../src/types/api-types";
import type { ChatMessage } from "../src/types/widget-types";
import { OnyxChatWidget } from "../src/widget";
import { mockFetch } from "./mocks";
import { chatStream, idle } from "./session-status";
import {
  bindings,
  shownText,
  skipPollPauses,
  waitUntil,
} from "./widget-helpers";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  mock.restore();
});

function question(id: string): ToolQuestionRequest {
  return {
    type: "tool_question_request",
    question_request_id: id,
    tool_call_id: `call-${id}`,
    questions: [
      {
        id: "env",
        header: "Environment",
        question: "Where should I deploy?",
        options: [
          { label: "Staging", description: "Safe to try changes." },
          { label: "Production", description: "Live for every user." },
        ],
      },
    ],
  };
}

function entry(
  id: string,
  resolution: QuestionResolution | null = null
): QuestionEntry {
  return { request: question(id), resolution };
}

const cardAnswers: ToolQuestionAnswer[] = [
  { question_id: "env", option_label: "Staging" },
];

function answered(
  id: string,
  how: { answers: ToolQuestionAnswer[] } | { message: string }
): QuestionResolution {
  return {
    type: "tool_question_resolved",
    question_request_id: id,
    outcome: "answered",
    ...("answers" in how
      ? { answered_via: "card", answers: how.answers }
      : { answered_via: "message", message: how.message }),
  };
}

function approval(id: string): ToolApprovalRequest {
  return {
    type: "tool_approval_request",
    approval_id: id,
    tool_call_id: `call-${id}`,
    tool_name: "send_email",
    display_name: "Send email",
    arguments: {},
  };
}

function waitingMessage(questions: QuestionEntry[]): ChatMessage {
  return {
    id: 7,
    role: "assistant",
    content: "",
    timestamp: 0,
    isStreaming: false,
    awaitingUser: true,
    questions,
  };
}

describe("question packets", () => {
  it("adds a request to the current response, or starts one, and keeps it at the answer's start", () => {
    const first = processPacket({ obj: question("q") }, null).message!;
    expect(first.role).toBe("assistant");
    expect(first.questions).toEqual([entry("q")]);

    const started = processPacket({ obj: { type: "message_start" } }, first);
    expect(started.message?.questions).toEqual([entry("q")]);
  });

  it("records a known outcome once and ignores an unknown one", () => {
    const current = { ...waitingMessage([entry("q"), entry("r")]) };
    const resolution: Packet = { obj: answered("q", { message: "Use staging" }) };
    const replayed = processPacket(resolution, current).message;
    expect(processPacket(resolution, replayed).message).toEqual(replayed);
    expect(replayed?.questions).toEqual([
      entry("q", answered("q", { message: "Use staging" })),
      entry("r"),
    ]);

    const unknown = processPacket(
      {
        obj: { ...answered("q", { answers: cardAnswers }), outcome: "deferred" },
      },
      current
    );
    expect(unknown.message).toBe(current);
  });

  it("marks a response that stops for the user as waiting", () => {
    const stopped = processPacket(
      { obj: { type: "stop", stop_reason: "awaiting_user" } },
      { ...waitingMessage([entry("q")]), isStreaming: true, awaitingUser: false }
    ).message;
    expect(stopped?.awaitingUser).toBe(true);
    expect(stopped?.isStreaming).toBe(false);
  });
});

describe("question status", () => {
  it("trusts the server resolution, then this widget's answer", () => {
    const card = answered("q", { answers: cardAnswers });
    expect(questionResolution(entry("q", card), "closed")).toBe(card);
    expect(questionResolution(entry("q"), card)).toBe(card);
    expect(questionResolution(entry("q"), "closed")?.outcome).toBe(
      "cancelled"
    );
    expect(questionResolution(entry("q"), "submitting")).toBeNull();
    expect(questionResolution(entry("q"), "failed")).toBeNull();
  });

  it("finds the first request or question that waits, in transcript order", () => {
    const agentApproval: ApprovalEntry = {
      request: { ...approval("c"), agent_name: "Research" },
      outcome: null,
    };
    const messages: ChatMessage[] = [
      {
        ...waitingMessage([entry("old", answered("old", { answers: cardAnswers }))]),
        approvals: [agentApproval],
      },
      waitingMessage([entry("q"), entry("r")]),
    ];
    const local = new Map([["q", "closed" as const]]);
    const wait = findPendingWait(messages, new Map(), local);
    expect(wait?.kind === "question" && wait.entry.request.question_request_id).toBe("r");

    messages[1] = {
      ...messages[1]!,
      approvals: [{ request: approval("a"), outcome: null }],
    };
    expect(findPendingWait(messages, new Map(), local)?.kind).toBe("approval");
  });

  it("builds answers only when every question has an option or a note", () => {
    const request = question("q");
    expect(draftAnswers(request, undefined)).toBeNull();
    expect(draftAnswers(request, { env: { note: "  " } })).toBeNull();
    expect(draftAnswers(request, { env: { option: "Staging" } })).toEqual(
      cardAnswers
    );
    expect(draftAnswers(request, { env: { note: " Both " } })).toEqual([
      { question_id: "env", user_note: "Both" },
    ]);
    // A question ID that names an inherited property has no choice yet.
    const named: ToolQuestionRequest = {
      ...request,
      questions: [
        request.questions[0]!,
        { ...request.questions[0]!, id: "constructor" },
      ],
    };
    expect(draftAnswers(named, { env: { option: "Staging" } })).toBeNull();
    expect(() =>
      renderQuestionCard(
        { request: named, resolution: null },
        null,
        view({ draft: { env: { option: "Staging" } } })
      )
    ).not.toThrow();
  });

  it("writes one line per answer, or one for a typed or cancelled answer", () => {
    const request = question("q");
    expect(
      questionRecords(request, answered("q", { answers: cardAnswers }))
    ).toEqual(["Environment: Staging"]);
    expect(
      questionRecords(
        request,
        answered("q", {
          answers: [
            { question_id: "env", option_label: "Staging", user_note: "first" },
          ],
        })
      )
    ).toEqual(["Environment: Staging - first"]);
    expect(
      questionRecords(request, answered("q", { message: "Use staging" }))
    ).toEqual(['Answered in the chat: "Use staging"']);
    expect(questionResolution(entry("q"), "closed")).not.toBeNull();
    expect(
      questionRecords(request, questionResolution(entry("q"), "closed")!)
    ).toEqual(["No longer waiting: Environment"]);
  });
});

function view(fields: Partial<QuestionCardView> = {}): QuestionCardView {
  return {
    submitting: false,
    failed: false,
    draft: undefined,
    page: 0,
    onChoose: () => {},
    onPage: () => {},
    onSubmit: () => {},
    ...fields,
  };
}

describe("question card", () => {
  it("shows each question with its options while it waits", () => {
    const text = shownText(renderQuestionCard(entry("q"), null, view()));
    for (const shown of [
      "The agent has a question",
      "Environment",
      "Where should I deploy?",
      "Staging",
      "Safe to try changes.",
      "Production",
      "Live for every user.",
    ]) {
      expect(text).toContain(shown);
    }
    expect(text).not.toContain("Could not submit");
    expect(
      shownText(renderQuestionCard(entry("q"), null, view({ failed: true })))
    ).toContain("Could not submit your answer. Try again.");
  });

  it("takes Other with a typed note, and enables Submit only once every question has an answer", () => {
    const request = question("q");
    let draft: QuestionDraft | undefined;
    const submitted: ToolQuestionRequest[] = [];
    const card = () =>
      bindings(
        renderQuestionCard(
          { request, resolution: null },
          null,
          view({
            draft,
            onChoose: (_request, questionId, choice) => {
              draft = { ...draft, [questionId]: choice };
            },
            onSubmit: (chosen) => void submitted.push(chosen),
          })
        )
      );
    const handler = (name: string, nth = -1) => {
      const found = card().filter((binding) => binding.name === name);
      return found.at(nth)!.value as (event?: unknown) => void;
    };
    const submitDisabled = () =>
      card().filter((binding) => binding.name === "?disabled").at(-1)!.value;

    expect(submitDisabled()).toBe(true);
    // Options first, then Other
    expect(card().filter((binding) => binding.name === "@change")).toHaveLength(
      3
    );
    handler("@change")();
    expect(draft).toEqual({ env: { note: "" } });
    expect(submitDisabled()).toBe(true);

    handler("@input")({ target: { value: "Both" } });
    expect(submitDisabled()).toBe(false);
    // Enter that confirms an IME candidate does not submit.
    const enter = (isComposing: boolean) =>
      handler("@keydown")({
        key: "Enter",
        isComposing,
        preventDefault: () => {},
        stopPropagation: () => {},
      });
    enter(true);
    expect(submitted).toEqual([]);
    enter(false);
    expect(submitted).toEqual([request]);
    submitted.length = 0;
    handler("@click")();
    expect(submitted).toEqual([request]);
    expect(draftAnswers(request, draft)).toEqual([
      { question_id: "env", user_note: "Both" },
    ]);

    handler("@change", 0)();
    expect(draft).toEqual({ env: { option: "Staging" } });
    expect(card().some((binding) => binding.name === "@input")).toBe(false);
  });

  it("shows one question per page, keeps choices across pages, and enables Submit once every question has an answer", () => {
    const base = question("q");
    const request: ToolQuestionRequest = {
      ...base,
      questions: [
        base.questions[0]!,
        {
          id: "region",
          header: "Region",
          question: "Which region?",
          options: [
            { label: "US", description: "" },
            { label: "EU", description: "" },
          ],
        },
        {
          id: "notify",
          header: "Notify",
          question: "Who should I tell?",
          options: [{ label: "Team", description: "" }],
        },
      ],
    };
    let draft: QuestionDraft | undefined;
    let page = 0;
    const submitted: ToolQuestionRequest[] = [];
    const rendered = () =>
      renderQuestionCard(
        { request, resolution: null },
        null,
        view({
          draft,
          page,
          onChoose: (_request, questionId, choice) => {
            draft = { ...draft, [questionId]: choice };
          },
          onPage: (_request, next) => {
            page = next;
          },
          onSubmit: (chosen) => void submitted.push(chosen),
        })
      );
    const card = () => bindings(rendered());
    const text = () => shownText(rendered());
    const named = (name: string) =>
      card().filter((binding) => binding.name === name);
    const click = (nth: number) =>
      (named("@click").at(nth)!.value as () => void)();
    const choose = (nth: number) =>
      (named("@change").at(nth)!.value as () => void)();
    // The fieldset, Back, then Next or Submit
    const disabled = () => named("?disabled").map((binding) => binding.value);
    const optionChecked = () => named(".checked").map((binding) => binding.value);

    expect(text()).toContain("Question 1 of 3");
    expect(text()).toContain("Where should I deploy?");
    expect(text()).not.toContain("Which region?");
    expect(text()).toContain("Next");
    expect(text()).not.toContain("Submit");
    expect(disabled()).toEqual([false, true, false]);

    click(-1);
    expect(page).toBe(1);
    expect(text()).toContain("Question 2 of 3");
    expect(text()).toContain("Which region?");
    expect(optionChecked()).toEqual([false, false, false]);
    choose(1);
    expect(page).toBe(1);
    expect(draft).toEqual({ region: { option: "EU" } });

    click(-1);
    expect(page).toBe(2);
    expect(text()).toContain("Submit");
    expect(text()).not.toContain("Next");
    expect(disabled()).toEqual([false, false, true]);
    expect(text()).toContain("Answer questions 1 and 3 to submit.");
    const hintId = named("id").at(-1)!.value;
    expect(hintId).toBe(`question-unanswered-${request.question_request_id}`);
    expect(named("aria-describedby").at(-1)!.value).toBe(hintId);

    click(0);
    expect(page).toBe(1);
    expect(optionChecked()).toEqual([false, true, false]);
    click(0);
    expect(page).toBe(0);
    expect(disabled()[1]).toBe(true);
    choose(1);

    page = 2;
    choose(-1);
    expect(text()).toContain("Answer question 3 to submit.");
    (named("@input").at(0)!.value as (event: unknown) => void)({
      target: { value: "Ops" },
    });
    expect(text()).not.toContain("to submit");
    expect(named("id")).toEqual([]);
    expect(named("aria-describedby").at(-1)!.value).toBe(nothing);
    expect(disabled()).toEqual([false, false, false]);
    click(-1);
    expect(submitted).toEqual([request]);
    expect(draftAnswers(request, draft)).toEqual([
      { question_id: "env", option_label: "Production" },
      { question_id: "region", option_label: "EU" },
      { question_id: "notify", user_note: "Ops" },
    ]);
  });

  it("shows no page navigation for one question", () => {
    const text = shownText(renderQuestionCard(entry("q"), null, view()));
    expect(text).not.toContain("Question 1 of 1");
    expect(text).not.toContain("Back");
    expect(text).not.toContain("Next");
    expect(text).toContain("Submit");
  });

  it("shows one line per answer once the question ends", () => {
    const text = shownText(
      renderQuestionCard(
        entry("q"),
        answered("q", { answers: cardAnswers }),
        view()
      )
    );
    expect(text).toContain("Environment: Staging");
    expect(text).not.toContain("Where should I deploy?");
  });
});

describe("question answers", () => {
  it("posts card answers with the widget credential", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    mockFetch(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return Response.json({
        question_request_id: "q/1",
        continuation: { stream_id: 9, response_ids: [7] },
      });
    });
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(
      await api.submitQuestionAnswers("q/1", { answers: cardAnswers })
    ).toEqual({ continuation: { stream_id: 9, response_ids: [7] } });
    expect(calls[0]!.url).toBe(
      "https://onyx.test/api/chat/question-requests/q%2F1/answers"
    );
    expect(calls[0]!.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0]!.init?.body))).toEqual({
      answers: cardAnswers,
    });
    expect(new Headers(calls[0]!.init?.headers).get("Authorization")).toBe(
      "Bearer key"
    );
  });

  it("posts a typed message and reads no continuation", async () => {
    let body: unknown;
    mockFetch(async (_input: RequestInfo | URL, init?: RequestInit) => {
      body = JSON.parse(String(init?.body));
      return Response.json({ question_request_id: "q", continuation: null });
    });
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(
      await api.submitQuestionAnswers("q", { message: "Use staging" })
    ).toEqual({ continuation: null });
    expect(body).toEqual({ message: "Use staging" });
  });

  it.each([
    [404, "NOT_FOUND"],
    [409, "CONFLICT"],
  ])("reports a question that no longer waits (%s)", async (status, code) => {
    mockFetch(async () =>
      Response.json({ error_code: code, detail: "gone" }, { status })
    );
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(
      await api.submitQuestionAnswers("q", { answers: cardAnswers })
    ).toBe("closed");
  });

  it("throws the pending-approval conflict and other failures", async () => {
    const responses = [
      Response.json(
        { error_code: APPROVAL_PENDING_ERROR_CODE, detail: "waiting" },
        { status: 409 }
      ),
      new Response("boom", { status: 500 }),
    ];
    mockFetch(async () => responses.shift()!);
    const api = new ApiService("https://onyx.test/api", async () => "key");
    const blocked = await api
      .submitQuestionAnswers("q", { message: "hi" })
      .catch((e: unknown) => e);
    expect(blocked).toBeInstanceOf(ApiError);
    expect((blocked as ApiError).errorCode).toBe(APPROVAL_PENDING_ERROR_CODE);
    await expect(
      api.submitQuestionAnswers("q", { answers: cardAnswers })
    ).rejects.toThrow();
  });
});

describe("widget while a question waits", () => {
  /** The session's response 7 stopped while `questions` wait. */
  function waitingWidget(questions: QuestionEntry[] = [entry("q")]) {
    skipPollPauses();
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["currentIdentity"] = async () => "user";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    widget["apiService"] = api;
    widget["chatSessionId"] = "session";
    widget["messages"] = [waitingMessage(questions)];
    // The suspended response has no running stream.
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      return "noBuffer";
    });
    api.waitForSessionIdle = mock(async () => idle());
    api.getChatSession = mock(
      async (): Promise<ChatSessionDetail> => ({ messages: [], packets: [] })
    );
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      throw new Error("A send must not start while a question waits");
    });
    return { widget, api };
  }

  const resolution = (widget: OnyxChatWidget, id: string) => {
    const found = widget["messages"]
      .flatMap((message) => message.questions ?? [])
      .find((item) => item.request.question_request_id === id)!;
    return questionResolution(found, widget["localQuestions"].get(id));
  };

  it("submits the card's choices and follows the continuation from its start", async () => {
    const { widget, api } = waitingWidget();
    api.submitQuestionAnswers = mock(async () => ({
      continuation: chatStream(9, [7]),
    }));
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor
    > {
      yield { stream_id: 9, next_cursor: 0, replay_complete: false };
      yield { obj: { user_message_id: 6, reserved_assistant_message_id: 7 } };
      yield { obj: question("q") };
      yield { obj: answered("q", { answers: cardAnswers }) };
      yield { obj: { type: "replay_end" } };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Deployed." } };
      yield { obj: { type: "stop" } };
    });

    widget["chooseAnswer"](question("q"), "env", { option: "Staging" });
    const answers = draftAnswers(
      question("q"),
      widget["questionDrafts"].get("q")
    )!;
    await widget["answerQuestions"](question("q"), { answers });
    await waitUntil(() => widget["messages"][0]?.content === "Deployed.");

    expect(api.submitQuestionAnswers).toHaveBeenCalledWith("q", {
      answers: cardAnswers,
    });
    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      { streamId: 9, cursor: 0 }
    );
    expect(resolution(widget, "q")?.answers).toEqual(cardAnswers);
    expect(widget["localQuestions"].size).toBe(0);
    expect(widget["questionDrafts"].size).toBe(0);
    expect(widget["pendingWait"]).toBeNull();
  });

  it("answers every waiting question of the response with a typed message instead of sending it", async () => {
    const { widget, api } = waitingWidget([entry("q"), entry("r")]);
    api.submitQuestionAnswers = mock(async () => ({ continuation: null }));
    widget["inputValue"] = " Use staging ";

    await widget["sendMessage"]();

    expect(api.streamMessage).not.toHaveBeenCalled();
    expect(api.submitQuestionAnswers).toHaveBeenCalledTimes(1);
    expect(api.submitQuestionAnswers).toHaveBeenCalledWith("q", {
      message: "Use staging",
    });
    expect(widget["inputValue"]).toBe("");
    expect(widget["error"]).toBeUndefined();
    expect(resolution(widget, "q")?.answered_via).toBe("message");
    expect(resolution(widget, "r")?.answered_via).toBe("message");
    expect(resolution(widget, "q")?.message).toBe("Use staging");
    // Nothing waits, so the response's next stream is followed.
    await waitUntil(
      () => (api.resumeStream as ReturnType<typeof mock>).mock.calls.length > 0
    );
  });

  it("keeps the draft and points at the approval when one of the response still waits", async () => {
    const { widget, api } = waitingWidget();
    Object.defineProperty(widget, "isConnected", { value: true });
    Object.defineProperty(widget, "updateComplete", {
      value: Promise.resolve(true),
    });
    const pointed: string[] = [];
    widget["pointAtWait"] = (wait) =>
      void pointed.push(
        wait.kind === "approval"
          ? wait.entry.request.approval_id
          : wait.entry.request.question_request_id
      );
    api.submitQuestionAnswers = mock(async () => {
      throw new ApiError("waiting", 409, APPROVAL_PENDING_ERROR_CODE);
    });
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        { message_id: 7, message_type: "assistant", parent_message: 6 },
      ],
      packets: [
        [
          { obj: approval("a") },
          { obj: question("q") },
          { obj: { type: "stop", stop_reason: "awaiting_user" } },
        ],
      ],
    }));
    widget["inputValue"] = "Use staging";

    await widget["sendMessage"]();

    expect(api.streamMessage).not.toHaveBeenCalled();
    expect(widget["inputValue"]).toBe("Use staging");
    expect(widget["error"]).toBe(
      "Approve or reject the pending tool calls first."
    );
    expect(api.getChatSession).toHaveBeenCalled();
    expect(widget["localQuestions"].size).toBe(0);
    expect(pointed).toEqual(["a"]);
  });

  it("keeps the draft when a typed answer fails", async () => {
    const { widget, api } = waitingWidget();
    api.submitQuestionAnswers = mock(async () => {
      throw new Error("offline");
    });
    widget["inputValue"] = "Use staging";

    await widget["sendMessage"]();

    expect(widget["inputValue"]).toBe("Use staging");
    expect(widget["error"]).toBe("Could not send your answer. Try again.");
    expect(widget["pendingWait"]?.kind).toBe("question");
  });

  it("shows the server's refusal of a typed answer as a send error", async () => {
    const { widget, api } = waitingWidget();
    api.submitQuestionAnswers = mock(async () => {
      throw new ApiError("Not allowed here", 400, "QUERY_REJECTED");
    });
    widget["inputValue"] = "Use staging";

    await widget["sendMessage"]();

    expect(widget["inputValue"]).toBe("Use staging");
    expect(widget["error"]).toBe("Not allowed here");
    expect(widget["localQuestions"].size).toBe(0);
  });

  it("keeps the card actionable after a failed answer", async () => {
    const { widget, api } = waitingWidget();
    api.submitQuestionAnswers = mock(async () => {
      throw new Error("offline");
    });

    await widget["answerQuestions"](question("q"), { answers: cardAnswers });

    expect(widget["localQuestions"].get("q")).toBe("failed");
    expect(widget["error"]).toBeUndefined();
    expect(widget["pendingWait"]?.kind).toBe("question");
    expect(api.resumeStream).not.toHaveBeenCalled();
  });

  it("shows a question that no longer waits and reads the status", async () => {
    const { widget, api } = waitingWidget();
    api.submitQuestionAnswers = mock(async () => "closed" as const);

    await widget["answerQuestions"](question("q"), { answers: cardAnswers });
    await waitUntil(() => widget["abortController"] === undefined);

    expect(resolution(widget, "q")?.outcome).toBe("cancelled");
    expect(api.waitForSessionIdle).toHaveBeenCalled();
    expect(api.resumeStream).not.toHaveBeenCalled();
  });

  it("shows a waiting question and a typed answer from the saved session", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [];
    widget["approvalsChanged"] = true;
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 4, message_type: "user", latest_child_message: 5 },
        {
          message_id: 5,
          message_type: "assistant",
          parent_message: 4,
          latest_child_message: 6,
        },
        {
          message_id: 6,
          message_type: "user",
          parent_message: 5,
          latest_child_message: 7,
        },
        { message_id: 7, message_type: "assistant", parent_message: 6 },
      ],
      packets: [
        [
          { obj: { type: "user_message", id: "sdk-1", message: "Deploy" } },
          { obj: question("old") },
          { obj: answered("old", { message: "Use staging" }) },
          { obj: { type: "message_start" } },
          { obj: { type: "message_delta", content: "Deployed." } },
          { obj: { type: "stop" } },
        ],
        [
          { obj: { type: "user_message", id: "sdk-2", message: "Again" } },
          { obj: question("q") },
          { obj: { type: "stop", stop_reason: "awaiting_user" } },
        ],
      ],
    }));

    await widget["resumeStream"]("session", { streamId: null });

    const [, first, , second] = widget["messages"];
    expect(
      questionRecords(question("old"), first!.questions![0]!.resolution!)
    ).toEqual(['Answered in the chat: "Use staging"']);
    expect(first!.content).toBe("Deployed.");
    expect(second!.awaitingUser).toBe(true);
    const wait = widget["pendingWait"];
    expect(wait?.kind === "question" && wait.entry.request.question_request_id).toBe("q");
  });
});
