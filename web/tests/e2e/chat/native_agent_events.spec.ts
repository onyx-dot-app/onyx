import { test } from "@playwright/test";
import { NativeChatPage } from "@tests/e2e/pages/NativeChatPage";
import { loginAs } from "@tests/e2e/utils/auth";
import {
  buildMockSearchStream,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";

function eventPacket(content: string, phase = "chat", turn = 1) {
  return {
    placement: { turn_index: turn, tab_index: 0 },
    obj: {
      type: "pydantic_ai",
      phase,
      event: {
        event_kind: "part_start",
        index: 0,
        part: { part_kind: "text", content },
      },
    },
  };
}
function nativeSearchStream(): string {
  const legacy = buildMockSearchStream({
    content: "Native answer with evidence [[D1]](https://example.com/native).",
    queries: ["native agent evidence"],
    documents: [
      {
        document_id: "native-doc",
        semantic_identifier: "Native evidence source",
        link: "https://example.com/native",
        source_type: "web",
        blurb: "Verified native agent evidence.",
        is_internet: true,
      },
    ],
    citations: { 1: "native-doc" },
    isInternetSearch: true,
  });
  const packets = legacy
    .trim()
    .split("\n")
    .flatMap((line) => {
      const packet = JSON.parse(line);
      if ("reserved_assistant_message_id" in packet)
        packet.type = "message_id_info";
      if (packet.placement) packet.placement.turn_index += 1;
      if (packet.obj?.type !== "message_start") return [packet];
      return [
        {
          placement: packet.placement,
          obj: {
            type: "answer_metadata",
            final_documents: packet.obj.final_documents,
          },
        },
        eventPacket(packet.obj.content, "chat", packet.placement.turn_index),
      ];
    });
  packets.splice(1, 0, {
    placement: { turn_index: 0, tab_index: 0 },
    obj: {
      type: "pydantic_ai",
      phase: "chat",
      event: {
        event_kind: "part_start",
        index: 0,
        part: { part_kind: "thinking", content: "Check the source evidence." },
      },
    },
  });
  return packets.map((packet) => JSON.stringify(packet)).join("\n") + "\n";
}
test.beforeEach(async ({ page }) => {
  resetTurnCounter();
  await loginAs(page, "admin");
});
test("native text, thinking, search sources and citations finish cleanly", async ({
  page,
}) => {
  const chat = new NativeChatPage(page);
  await page.route("**/api/chat/send-chat-message", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/plain",
      body: nativeSearchStream(),
    })
  );
  await chat.goto();
  await chat.send("Find evidence for this native agent answer");
  await chat.expectAnswer("Native answer with evidence");
  await chat.expectCitation();
  await chat.expandTimeline();
  await chat.expectStreamingText("Check the source evidence.");
  await chat.expectStopped();
});
test("stop cancels an open native event stream", async ({ page }) => {
  await page.addInitScript(
    (firstPackets) => {
      const originalFetch = window.fetch.bind(window);
      let activeStream: ReadableStreamDefaultController<Uint8Array> | undefined;
      window.fetch = async (...args) => {
        const request = args[0];
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        if (url.includes("/api/chat/stop-chat-session/")) {
          activeStream?.enqueue(
            new TextEncoder().encode(
              JSON.stringify({
                placement: { turn_index: 0, tab_index: 0 },
                obj: { type: "stop", stop_reason: "user_cancelled" },
              }) + "\n"
            )
          );
          activeStream?.close();
          return new Response("{}", { status: 200 });
        }
        if (!url.includes("/api/chat/send-chat-message"))
          return originalFetch(...args);
        return new Response(
          new ReadableStream({
            start(controller) {
              activeStream = controller;
              controller.enqueue(new TextEncoder().encode(firstPackets));
              const signal =
                args[1]?.signal ??
                (request instanceof Request ? request.signal : null);
              signal?.addEventListener("abort", () =>
                controller.error(new DOMException("Aborted", "AbortError"))
              );
            },
          }),
          { headers: { "Content-Type": "text/plain" } }
        );
      };
    },
    [
      {
        type: "message_id_info",
        user_message_id: 101,
        reserved_assistant_message_id: 102,
      },
      eventPacket("Native response before interruption.", "chat", 0),
    ]
      .map((packet) => JSON.stringify(packet))
      .join("\n") + "\n"
  );
  const chat = new NativeChatPage(page);
  await chat.goto();
  await chat.send("Start a native response");
  await chat.expectStreamingText("Native response before interruption.");
  await chat.stop();
  await chat.expectStopped();
});

test("saved native research phases and citations replay after reload", async ({
  page,
}) => {
  const sessionId = "a86d4d2c-7fad-4ab4-9689-6c763bed9075";
  const searchPackets = nativeSearchStream()
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const docs = searchPackets.find(
    (packet) => packet.obj?.type === "answer_metadata"
  ).obj.final_documents;
  const packets = [
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "deep_research_plan_start" },
    },
    eventPacket("Compare reliable sources for this research plan.", "plan", 0),
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "section_end" },
    },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "research_agent_start",
        research_task: "Verify source evidence",
      },
    },
    eventPacket("Intermediate research narration.", "research", 1),
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: "intermediate_report_start" },
    },
    eventPacket("The intermediate report confirms the evidence.", "report", 1),
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: "section_end" },
    },
    ...searchPackets
      .filter((packet) => packet.obj)
      .map((packet) => ({
        ...packet,
        placement: {
          ...packet.placement,
          turn_index: packet.placement.turn_index + 2,
        },
      })),
  ];
  const common = {
    research_type: "deep",
    rephrased_query: null,
    context_docs: [],
    time_sent: new Date().toISOString(),
    citations: {},
    files: [],
    tool_call: null,
    overridden_model: "test-model",
    alternate_assistant_id: null,
    chat_session_id: sessionId,
    current_feedback: null,
    error: null,
  };
  await page.route(`**/api/chat/get-chat-session/${sessionId}`, (route) =>
    route.fulfill({
      json: {
        chat_session_id: sessionId,
        description: "Native replay",
        persona_id: 0,
        persona_name: null,
        time_created: new Date().toISOString(),
        shared_status: "private",
        current_alternate_model: null,
        current_temperature_override: null,
        current_reasoning_effort_override: null,
        packets: [packets],
        messages: [
          {
            ...common,
            message_id: 101,
            message_type: "user",
            parent_message: null,
            latest_child_message: 102,
            message: "Research native events",
          },
          {
            ...common,
            message_id: 102,
            message_type: "assistant",
            parent_message: 101,
            latest_child_message: null,
            message: "Native answer with evidence.",
            context_docs: docs,
            citations: { 1: "native-doc" },
          },
        ],
      },
    })
  );
  const chat = new NativeChatPage(page);
  await page.goto(`/app?chatId=${sessionId}`);
  await chat.expectAnswer("Native answer with evidence");
  await chat.expectCitation();
  await chat.expandTimeline();
  await chat.expectStreamingText(
    "Compare reliable sources for this research plan."
  );
  await chat.expectStreamingText(
    "The intermediate report confirms the evidence."
  );
  await page.reload();
  await chat.expectAnswer("Native answer with evidence");
  await chat.expectCitation();
  await chat.expectStopped();
});
