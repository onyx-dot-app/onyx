import { expect, Page, Route } from "@playwright/test";
import { sendMessage } from "./chatActions";

export type ChatStreamObject = Record<string, unknown> & {
  type?: string;
};

export type ChatStreamPacket = Record<string, unknown> & {
  obj?: ChatStreamObject;
};

function parseStreamLine(rawLine: string): ChatStreamPacket | null {
  const trimmed = rawLine.trim();
  if (!trimmed) {
    return null;
  }

  const withoutPrefix = trimmed.startsWith("data:")
    ? trimmed.slice("data:".length).trim()
    : trimmed;
  if (!withoutPrefix || withoutPrefix === "[DONE]") {
    return null;
  }

  try {
    return JSON.parse(withoutPrefix) as ChatStreamPacket;
  } catch {
    return null;
  }
}

export function parseChatStreamBody(body: string): ChatStreamPacket[] {
  return body
    .split("\n")
    .map(parseStreamLine)
    .filter((packet): packet is ChatStreamPacket => packet !== null);
}

export function getPacketObjectsByType(
  packets: ChatStreamPacket[],
  packetType: string
): ChatStreamObject[] {
  return packets
    .map((packet) => packet.obj)
    .filter(
      (obj): obj is ChatStreamObject =>
        !!obj && typeof obj.type === "string" && obj.type === packetType
    );
}

export async function sendMessageAndCaptureStreamPackets(
  page: Page,
  message: string,
  options?: {
    mockLlmResponse?: string;
    payloadOverrides?: Record<string, unknown>;
    waitForAiMessage?: boolean;
  }
): Promise<ChatStreamPacket[]> {
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
      await page.locator("#onyx-chat-input-textarea").click();
      await page.locator("#onyx-chat-input-textarea").fill(message);
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
