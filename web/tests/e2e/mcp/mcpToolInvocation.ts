import { type Page, expect } from "@playwright/test";
import {
  getToolPacketCounts,
  sendMessageAndCaptureStreamPackets,
} from "@tests/e2e/utils/chatStream";
import { addMockLlmConversation, mockLlmNonce } from "@tests/e2e/utils/mockLlm";

/**
 * Send a chat message and return the tool's invocation packet counts. The mock LLM
 * calls the tool only when the request offers it.
 */
export async function sendMcpToolCall(
  page: Page,
  toolName: string
): Promise<{ start: number; delta: number; debug: number }> {
  const nonce = mockLlmNonce();
  const callId = `call-${nonce}`;
  await addMockLlmConversation({
    name: `mcp-${nonce}`,
    conditions: { prompt_contains: [nonce] },
    replies: [
      {
        tool_calls: [
          { id: callId, name: toolName, arguments: { name: nonce } },
        ],
        conditions: { offers: [toolName] },
      },
      { text: "Done.", conditions: { has_results_for: [callId] } },
    ],
  });

  const prompt = [
    `Call the MCP tool "${toolName}" now.`,
    `Pass {"name":"${nonce}"} as the arguments.`,
    "Return the exact tool output.",
  ].join(" ");

  const packets = await sendMessageAndCaptureStreamPackets(page, prompt, {
    waitForAiMessage: false,
  });

  return getToolPacketCounts(packets, toolName);
}

/** Assert the tool ran (start / delta / debug packets were all emitted). */
export async function expectMcpToolInvoked(
  page: Page,
  toolName: string
): Promise<void> {
  const counts = await sendMcpToolCall(page, toolName);
  expect(counts.start).toBeGreaterThan(0);
  expect(counts.delta).toBeGreaterThan(0);
  expect(counts.debug).toBeGreaterThan(0);
}

/** Assert the tool did NOT run (e.g. because it was disabled for the agent). */
export async function expectMcpToolNotInvoked(
  page: Page,
  toolName: string,
  excludedToolId: number
): Promise<void> {
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/chat/send-chat-message"
  );
  const counts = await sendMcpToolCall(page, toolName);
  expect((await requestPromise).postDataJSON()).toMatchObject({
    allowed_tool_ids: expect.not.arrayContaining([excludedToolId]),
    forced_tool_id: null,
  });
  expect(counts.start).toBe(0);
  expect(counts.delta).toBe(0);
  expect(counts.debug).toBe(0);
}
