import { renderHook, waitFor } from "@tests/setup/test-utils";
import type { BackendMessage } from "@/app/app/types";
import type { Packet } from "@/app/app/services/streamingModels";
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

const INSTRUCTION = message(10, "user", "Find the answer", null, 11);
const RESPONSE = message(11, "assistant", "", 10, null);

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
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
        return new Response(
          [
            JSON.stringify({
              stream_id: 7,
              next_cursor: 0,
              replay_complete: true,
            }),
            JSON.stringify(text("Live answer")),
            JSON.stringify({
              placement: { turn_index: 0 },
              obj: { type: "chat_heartbeat" },
            }),
          ].join("\n") + "\n"
        );
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
    urls.filter((url) => url.endsWith("/agents/agent-1/history"))
  ).toHaveLength(2);
});

test("the streamed packets replace the running response's saved ones while it streams", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/agents/agent-1/stream")) {
      // One line, then the stream stays open
      const line = new Uint8Array(
        await new Response(
          JSON.stringify(text("Live answer")) + "\n"
        ).arrayBuffer()
      );
      const reads = [
        Promise.resolve({ done: false, value: line }),
        new Promise<never>(() => {}),
      ];
      const response = new Response(null);
      Object.defineProperty(response, "body", {
        value: {
          getReader: () => ({
            read: () => reads.shift() ?? new Promise<never>(() => {}),
            cancel: () => Promise.resolve(),
          }),
        },
      });
      return response;
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
  expect(result.current.liveResponseId).toBe(11);
});
