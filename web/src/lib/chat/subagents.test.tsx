import { renderHook, waitFor } from "@tests/setup/test-utils";
import type { BackendMessage } from "@/app/app/types";
import { StopReason, type Packet } from "@/app/app/services/streamingModels";
import { useSubagentTranscript } from "@/lib/chat/subagents";

function message(
  id: number,
  type: "user" | "assistant",
  text: string,
  parent: number | null,
  child: number | null
): BackendMessage {
  return {
    message_id: id,
    message_type: type,
    research_type: null,
    parent_message: parent,
    latest_child_message: child,
    message: text,
    rephrased_query: null,
    context_docs: null,
    time_sent: "2026-11-25T00:00:00Z",
    overridden_model: "test",
    alternate_assistant_id: null,
    chat_session_id: "agent-1",
    citations: null,
    files: [],
    tool_call: null,
    current_feedback: null,
    sub_questions: [],
    comments: null,
    parentMessageId: null,
    refined_answer_improvement: null,
    is_agentic: null,
    preferred_response_id: null,
    model_display_name: null,
    error: null,
  };
}

function text(content: string): Packet {
  return {
    placement: { turn_index: 0 },
    obj: { type: "message_delta", content },
  };
}

const STOP: Packet = {
  placement: { turn_index: 0 },
  obj: { type: "stop", stop_reason: StopReason.FINISHED },
};

const INSTRUCTION = message(10, "user", "Find the answer", null, 11);
const RESPONSE = message(11, "assistant", "", 10, null);

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

/** An SSE body of these lines; `open` keeps it open after them. jsdom's
 *  Response has no readable body of its own. */
async function stream(lines: unknown[], open = false): Promise<Response> {
  const bytes = new Uint8Array(
    await new Response(
      lines.map((line) => JSON.stringify(line)).join("\n") + "\n"
    ).arrayBuffer()
  );
  const reads: Promise<{ done: boolean; value?: Uint8Array }>[] = [
    Promise.resolve({ done: false, value: bytes }),
  ];
  const response = new Response(null);
  Object.defineProperty(response, "body", {
    value: {
      getReader: () => ({
        read: () =>
          reads.shift() ??
          (open
            ? new Promise<never>(() => {})
            : Promise.resolve({ done: true })),
        cancel: () => Promise.resolve(),
      }),
    },
  });
  return response;
}

afterEach(() => jest.restoreAllMocks());

test("a running response shows its live stream, then its saved output once the stream ends", async () => {
  let streamEnded = false;
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/agents/agent-1/stream")) {
        streamEnded = true;
        return stream([
          { stream_id: 7, next_cursor: 0, replay_complete: true },
          text("Live answer"),
          { placement: { turn_index: 0 }, obj: { type: "chat_heartbeat" } },
          STOP,
          { stream_id: 7, next_cursor: 2, replay_complete: true },
        ]);
      }
      return json(
        streamEnded
          ? {
              messages: [INSTRUCTION, { ...RESPONSE, message: "Saved" }],
              packets: [[text("Saved answer")]],
              stream: null,
            }
          : {
              messages: [INSTRUCTION, RESPONSE],
              packets: [[]],
              stream: { stream_id: 7, response_ids: [11] },
            }
      );
    });

  const { result } = renderHook(() =>
    useSubagentTranscript("chat-1", "agent-1", null)
  );

  await waitFor(() => {
    const response = result.current.messages.find(
      (item) => item.messageId === 11
    );
    expect(response?.packets).toEqual([text("Saved answer")]);
  });
  expect(result.current.messages[0]?.message).toBe("Find the answer");
  const urls = fetchSpy.mock.calls.map(([url]) => String(url));
  expect(urls).toContain(
    "/api/chat/chat-session/chat-1/agents/agent-1/stream?stream_id=7&cursor=0"
  );
  // The history loaded again after the stream
  expect(
    urls.filter((url) => url.endsWith("/agents/agent-1/history")).length
  ).toBeGreaterThanOrEqual(2);
});

test("a dropped stream resumes from its last cursor", async () => {
  const streamCalls: string[] = [];
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/agents/agent-1/stream")) {
      streamCalls.push(url);
      // The first connection drops after one batch, before the stop
      const lines =
        streamCalls.length === 1
          ? [
              { stream_id: 7, next_cursor: 0, replay_complete: true },
              text("Part one"),
              { stream_id: 7, next_cursor: 1, replay_complete: true },
            ]
          : [
              { stream_id: 7, next_cursor: 1, replay_complete: true },
              text("Part two"),
              STOP,
              { stream_id: 7, next_cursor: 3, replay_complete: true },
            ];
      return stream(lines);
    }
    return json({
      messages: [INSTRUCTION, RESPONSE],
      packets: [[]],
      stream: { stream_id: 7, response_ids: [11] },
    });
  });

  const { result } = renderHook(() =>
    useSubagentTranscript("chat-1", "agent-1", 7)
  );

  await waitFor(
    () =>
      expect(
        result.current.messages.find((item) => item.messageId === 11)?.packets
      ).toEqual([text("Part one"), text("Part two"), STOP]),
    { timeout: 3000 }
  );
  expect(streamCalls).toEqual([
    "/api/chat/chat-session/chat-1/agents/agent-1/stream?stream_id=7&cursor=0",
    "/api/chat/chat-session/chat-1/agents/agent-1/stream?stream_id=7&cursor=1",
  ]);
});

test("a follow-up run that the parent's message started shows after the first reply", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async () =>
    json({
      // The first reply never links to the next instruction
      messages: [
        INSTRUCTION,
        { ...RESPONSE, message: "First" },
        message(12, "user", "Now check it", 11, 13),
        message(13, "assistant", "Second", 12, null),
      ],
      packets: [[text("First")], [text("Second")]],
      stream: null,
    })
  );

  const { result } = renderHook(() =>
    useSubagentTranscript("chat-1", "agent-1", null)
  );

  await waitFor(() =>
    expect(result.current.messages.map((item) => item.message)).toEqual([
      "Find the answer",
      "First",
      "Now check it",
      "Second",
    ])
  );
});

test("the streamed packets replace the running response's saved ones while it streams", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/agents/agent-1/stream")) {
      // One batch, then the stream stays open
      return stream(
        [
          { stream_id: 7, next_cursor: 0, replay_complete: true },
          text("Live answer"),
          { stream_id: 7, next_cursor: 1, replay_complete: true },
        ],
        true
      );
    }
    return json({
      messages: [INSTRUCTION, RESPONSE],
      packets: [[]],
      stream: { stream_id: 7, response_ids: [11] },
    });
  });

  const { result } = renderHook(() =>
    useSubagentTranscript("chat-1", "agent-1", 7)
  );

  await waitFor(() =>
    expect(
      result.current.messages.find((item) => item.messageId === 11)?.packets
    ).toEqual([text("Live answer")])
  );
});

test("packets that a drop cut off from their cursor land once, when the stream resends them", async () => {
  const streamCalls: string[] = [];
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/agents/agent-1/stream")) {
      streamCalls.push(url);
      // The first connection drops after a packet, before its cursor
      const lines =
        streamCalls.length === 1
          ? [
              { stream_id: 7, next_cursor: 0, replay_complete: true },
              text("Part one"),
            ]
          : [
              { stream_id: 7, next_cursor: 0, replay_complete: true },
              text("Part one"),
              text("Part two"),
              { stream_id: 7, next_cursor: 2, replay_complete: true },
              STOP,
              { stream_id: 7, next_cursor: 3, replay_complete: true },
            ];
      return stream(lines);
    }
    return json({
      messages: [INSTRUCTION, RESPONSE],
      packets: [[]],
      stream: { stream_id: 7, response_ids: [11] },
    });
  });

  const { result } = renderHook(() =>
    useSubagentTranscript("chat-1", "agent-1", 7)
  );

  await waitFor(
    () =>
      expect(
        result.current.messages.find((item) => item.messageId === 11)?.packets
      ).toEqual([text("Part one"), text("Part two"), STOP]),
    { timeout: 3000 }
  );
  expect(streamCalls).toHaveLength(2);
  expect(streamCalls[1]).toContain("cursor=0");
});
