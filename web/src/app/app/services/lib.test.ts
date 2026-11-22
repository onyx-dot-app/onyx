/** @jest-environment jsdom */

import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SessionEndReason } from "@/lib/auth/types";
import { createChatSession, sendMessage } from "@/app/app/services/lib";
import { MAX_MENTIONS_PER_MESSAGE } from "@/lib/chat/types";

jest.mock("swr", () => ({ mutate: jest.fn() }));

const mockedMutate = jest.mocked(mutate);

function jsonResponse(status: number, body: object): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function drainSendMessage(): Promise<void> {
  const stream = sendMessage({
    message: "hello",
    parentMessageId: null,
    chatSessionId: "chat-session-id",
    toolOptions: {
      allowed: null,
      preferred: null,
      internal_search_filters: null,
    },
  });
  for await (const _packet of stream) {
    // The tests only check the failure path.
  }
}

beforeEach(() => {
  mockedMutate.mockReset();
});

afterEach(() => jest.restoreAllMocks());

describe("session-ended 403", () => {
  test("sendMessage refetches /api/me and still throws", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(
      jsonResponse(403, {
        error_code: SessionEndReason.TERMINATED,
        detail: "Session terminated",
      })
    );

    await expect(drainSendMessage()).rejects.toThrow("Session terminated");
    expect(mockedMutate).toHaveBeenCalledWith(SWR_KEYS.me);
  });

  test("createChatSession refetches /api/me and still throws", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(
        jsonResponse(403, { error_code: SessionEndReason.EXPIRED })
      );
    jest.spyOn(console, "error").mockImplementation(() => {});

    await expect(createChatSession(0, null, null)).rejects.toThrow(
      "Failed to create chat session"
    );
    expect(mockedMutate).toHaveBeenCalledWith(SWR_KEYS.me);
  });

  test("a permission 403 does not refetch /api/me", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(
        jsonResponse(403, { error_code: "INSUFFICIENT_PERMISSIONS" })
      );
    jest.spyOn(console, "error").mockImplementation(() => {});

    await expect(createChatSession(0, null, null)).rejects.toThrow();
    await expect(drainSendMessage()).rejects.toThrow();
    expect(mockedMutate).not.toHaveBeenCalled();
  });
});

test("sendMessage sends each mention once, up to the per-message limit", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(""));
  const names = Array.from(
    { length: MAX_MENTIONS_PER_MESSAGE + 1 },
    (_, index) => `skill-${index}`
  );
  const stream = sendMessage({
    message: "hello",
    parentMessageId: null,
    chatSessionId: "chat-session-id",
    toolOptions: {
      allowed: null,
      preferred: null,
      internal_search_filters: null,
    },
    mentions: [...names, names[0]!].map((name) => ({ type: "skill", name })),
  });
  // Only the request matters, so the empty response's stream error does not.
  await stream.next().catch(() => undefined);

  const body = JSON.parse(String(fetchSpy.mock.calls[0]![1]!.body));
  expect(body.mentions).toEqual(
    names
      .slice(0, MAX_MENTIONS_PER_MESSAGE)
      .map((name) => ({ type: "skill", name }))
  );
});
