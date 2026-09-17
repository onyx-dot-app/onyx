/** Verify MCP execution through the public tool-item lifecycle. */

import { type Page, expect } from "@playwright/test";
import {
  getToolInvocationCounts,
  sendMessageAndCaptureStreamPackets,
  type ToolInvocationCounts,
} from "@tests/e2e/utils/chatStream";

/** Force a tool call and count distinct started and finished executions. */
export async function sendForcedMcpToolCall(
  page: Page,
  toolName: string,
  forcedToolId?: number | null
): Promise<ToolInvocationCounts> {
  const argName = `playwright-${Date.now()}`;
  const prompt = [
    `Call the MCP tool "${toolName}" now.`,
    `Pass {"name":"${argName}"} as the arguments.`,
    "Return the exact tool output.",
  ].join(" ");

  const packets = await sendMessageAndCaptureStreamPackets(page, prompt, {
    mockLlmResponse: JSON.stringify({
      name: toolName,
      arguments: { name: argName },
    }),
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
