import { expect, Page, Route } from "@playwright/test";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import type { Packet } from "@/app/app/services/streamingModels";
import type { PacketType } from "@/app/app/services/lib";

function parseStreamLine(rawLine: string): Packet | null {
  const trimmed = rawLine.trim();
  const line = trimmed.startsWith("data:")
    ? trimmed.slice("data:".length).trim()
    : trimmed;
  if (!line || line === "[DONE]") return null;
  const packet: PacketType = JSON.parse(line);
  return "obj" in packet ? packet : null;
}

export function parseChatStreamBody(body: string): Packet[] {
  return body
    .split("\n")
    .map(parseStreamLine)
    .filter((packet): packet is Packet => packet !== null);
}

export interface ToolInvocationCounts {
  started: number;
  finished: number;
}

/** Count distinct executions; repeated snapshots do not create another invocation. */
export function getToolInvocationCounts(
  packets: Packet[],
  toolName: string
): ToolInvocationCounts {
  const started = new Set<string>();
  const finished = new Set<string>();
  for (const packet of packets) {
    if (packet.obj.type !== "item_update") continue;
    const item = packet.obj.item;
    if (item.kind !== "tool" || item.name !== toolName) continue;
    const identity = packet.identity;
    if (!identity?.tool_call_id)
      throw new Error("Tool update has no invocation identity");
    const key = JSON.stringify([
      identity.response_id,
      identity.run_id,
      identity.message_id,
      identity.tool_call_id,
    ]);
    if (item.status === "running") started.add(key);
    else if (item.status !== "pending") finished.add(key);
  }
  return { started: started.size, finished: finished.size };
}

export async function sendMessageAndCaptureStreamPackets(
  page: Page,
  message: string,
  options?: {
    mockLlmResponse?: string;
    payloadOverrides?: Record<string, unknown>;
    waitForAiMessage?: boolean;
  }
): Promise<Packet[]> {
  const requestUrlPattern = "**/api/chat/send-chat-message";
  const mockLlmResponse = options?.mockLlmResponse;
  const payloadOverrides = options?.payloadOverrides;
  const waitForAiMessage = options?.waitForAiMessage ?? true;
  const routeHandler = async (route: Route) => {
    if (!mockLlmResponse && !payloadOverrides) {
      await route.continue();
      return;
    }

    const request = route.request();
    const payload = request.postDataJSON() as Record<string, unknown>;
    if (payloadOverrides) {
      Object.assign(payload, payloadOverrides);
    }
    if (mockLlmResponse) {
      payload.mock_llm_response = mockLlmResponse;
    }

    await route.continue({
      postData: JSON.stringify(payload),
      headers: {
        ...request.headers(),
        "content-type": "application/json",
      },
    });
  };

  await page.route(requestUrlPattern, routeHandler);

  const responsePromise = page.waitForResponse((response) => {
    if (
      response.request().method() !== "POST" ||
      !response.url().includes("/api/chat/send-chat-message")
    ) {
      return false;
    }

    const requestBody = response.request().postData();
    if (!requestBody) {
      return true;
    }

    try {
      const payload = JSON.parse(requestBody) as Record<string, unknown>;
      return payload.message === message;
    } catch {
      return true;
    }
  });

  try {
    if (waitForAiMessage) {
      await sendMessage(page, message);
    } else {
      await page.locator("#onyx-chat-input-textbox").click();
      await page.locator("#onyx-chat-input-textbox").fill(message);
      await page.locator("#onyx-chat-input-send-button").click();
      await page
        .waitForFunction(() => window.location.href.includes("chatId="), null, {
          timeout: 10000,
        })
        .catch(() => {});
    }

    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
    const body = await response.text();
    return parseChatStreamBody(body);
  } finally {
    await page.unroute(requestUrlPattern, routeHandler);
  }
}
