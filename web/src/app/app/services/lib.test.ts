/** @jest-environment jsdom */

import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SessionEndReason } from "@/lib/auth/types";
import { createChatSession, sendMessage } from "@/app/app/services/lib";

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
    filters: null,
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
