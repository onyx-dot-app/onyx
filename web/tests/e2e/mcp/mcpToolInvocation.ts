/**
 * Helpers for asserting whether an MCP tool actually runs when invoked from
 * chat. Wraps the chat-stream capture + packet-count utilities with the
 * forced-tool plumbing the MCP specs use.
 */

import { type Page, expect } from "@playwright/test";
import {
  getToolPacketCounts,
  sendMessageAndCaptureStreamPackets,
} from "@tests/e2e/utils/chatStream";

/**
 * Send a chat message that forces the given MCP tool to be called and return
 * the per-tool invocation packet counts (start / delta / debug).
 */
export async function sendForcedMcpToolCall(
  page: Page,
  toolName: string,
  forcedToolId?: number | null
): Promise<{ start: number; delta: number; debug: number }> {
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

  return getToolPacketCounts(packets, toolName);
}

/** Assert the tool ran (start / delta / debug packets were all emitted). */
export async function expectMcpToolInvoked(
  page: Page,
  toolName: string,
  forcedToolId?: number | null
): Promise<void> {
  const counts = await sendForcedMcpToolCall(page, toolName, forcedToolId);
  expect(counts.start).toBeGreaterThan(0);
  expect(counts.delta).toBeGreaterThan(0);
  expect(counts.debug).toBeGreaterThan(0);
}

/** Assert the tool did NOT run (e.g. because it was disabled for the agent). */
export async function expectMcpToolNotInvoked(
  page: Page,
  toolName: string,
  forcedToolId?: number | null
): Promise<void> {
  const counts = await sendForcedMcpToolCall(page, toolName, forcedToolId);
  expect(counts.start).toBe(0);
  expect(counts.delta).toBe(0);
  expect(counts.debug).toBe(0);
}
