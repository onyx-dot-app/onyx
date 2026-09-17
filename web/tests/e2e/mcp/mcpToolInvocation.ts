/** Verify MCP execution through the public tool-item lifecycle. */

import { type Page, expect } from "@playwright/test";
import {
  getToolInvocationCounts,
  sendMessageAndCaptureStreamPackets,
  type ToolInvocationCounts,
} from "@tests/e2e/utils/chatStream";
import { addMockLlmConversation, mockLlmNonce } from "@tests/e2e/utils/mockLlm";

/** Force a tool call and count distinct started and finished executions. */
export async function sendForcedMcpToolCall(
  page: Page,
  toolName: string,
  forcedToolId?: number | null
): Promise<ToolInvocationCounts> {
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
    payloadOverrides:
      forcedToolId != null
        ? { forced_tool_id: forcedToolId, forced_tool_ids: [forcedToolId] }
        : undefined,
    waitForAiMessage: false,
  });

  return getToolInvocationCounts(packets, toolName);
}

/** Assert that each started invocation reaches a terminal state. */
export async function expectMcpToolInvoked(
  page: Page,
  toolName: string,
  forcedToolId?: number | null
): Promise<void> {
  const counts = await sendForcedMcpToolCall(page, toolName, forcedToolId);
  expect(counts.started).toBeGreaterThan(0);
  expect(counts.finished).toBe(counts.started);
}

/** Assert the tool did NOT run (e.g. because it was disabled for the agent). */
export async function expectMcpToolNotInvoked(
  page: Page,
  toolName: string,
  forcedToolId?: number | null
): Promise<void> {
  const counts = await sendForcedMcpToolCall(page, toolName, forcedToolId);
  expect(counts.started).toBe(0);
  expect(counts.finished).toBe(0);
}
