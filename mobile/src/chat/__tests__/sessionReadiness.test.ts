import { afterEach, describe, expect, it, jest } from "@jest/globals";
import { ApiError } from "@/api/errors";
import { getChatSessionStatus } from "@/api/chat/sessions";
import type { Message } from "@/chat/interfaces";
import { waitForSessionIdle } from "@/chat/sessionReadiness";
import { useChatSessionStore } from "@/state/chatSessionStore";

jest.mock("@/api/chat/sessions", () => ({
  getChatSession: jest.fn(),
  getChatSessionStatus: jest.fn(),
}));
afterEach(() => {
  jest.useRealTimers();
  jest.resetAllMocks();
  useChatSessionStore.setState({ currentSessionId: null, sessions: new Map() });
});

describe("session readiness", () => {
  it("retries busy and failed checks without declaring idle", async () => {
    jest.useFakeTimers();
    const status = jest.mocked(getChatSessionStatus);
    status
      .mockResolvedValueOnce({ is_processing: true })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ is_processing: false });
    const unconfirmed = jest.fn();
    let settled = false;
    const pending = waitForSessionIdle("s", () => true, unconfirmed).then(
      (wait) => {
        settled = wait.kind === "idle";
      },
    );
    await jest.advanceTimersByTimeAsync(1000);
    expect(settled).toBe(false);
    expect(unconfirmed).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(1000);
    await pending;
    expect(settled).toBe(true);
  });

  it("ignores results once a newer request owns the session", async () => {
    let current = true;
    jest.mocked(getChatSessionStatus).mockImplementationOnce(async () => {
      current = false;
      return { is_processing: false };
    });
    expect(await waitForSessionIdle("s", () => current, jest.fn())).toEqual({
      kind: "released",
    });
  });

  it("returns the running stream that the caller follows", async () => {
    jest.useFakeTimers();
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: true, current_stream: null })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 7, response_ids: [7] },
      })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 8, response_ids: [8] },
      });
    const pending = waitForSessionIdle(
      "s",
      () => true,
      jest.fn(),
      (streamId) => streamId !== 7,
    );
    await jest.advanceTimersByTimeAsync(2000);
    expect(await pending).toEqual({
      kind: "stream",
      stream: { stream_id: 8, response_ids: [8] },
    });
    expect(getChatSessionStatus).toHaveBeenCalledTimes(3);
  });

  it("reports approvals that the shown load does not hold", async () => {
    const status = jest.mocked(getChatSessionStatus);
    // A chat that no load established, such as one this device created, has the empty
    // baseline that the server reports while the chat has no approval request.
    status.mockResolvedValueOnce({
      is_processing: false,
      approvals_version: "",
    });
    expect(
      await waitForSessionIdle("versioned", () => true, jest.fn()),
    ).toEqual({ kind: "idle", stale: false, backgroundWork: false });

    // An agent asked before this chat's first load.
    status.mockResolvedValueOnce({
      is_processing: false,
      approvals_version: "v1",
    });
    expect(
      await waitForSessionIdle("versioned", () => true, jest.fn()),
    ).toEqual({ kind: "idle", stale: true, backgroundWork: false });

    // A read alone does not show the requests, so the version stays changed.
    status.mockResolvedValueOnce({
      is_processing: false,
      approvals_version: "v1",
    });
    expect(
      await waitForSessionIdle("versioned", () => true, jest.fn()),
    ).toEqual({ kind: "idle", stale: true, backgroundWork: false });

    useChatSessionStore.getState().hydrateSession("versioned", new Map(), "v1");
    status.mockResolvedValueOnce({
      is_processing: false,
      approvals_version: "v1",
    });
    expect(
      await waitForSessionIdle("versioned", () => true, jest.fn()),
    ).toEqual({ kind: "idle", stale: false, backgroundWork: false });

    status.mockResolvedValueOnce({
      is_processing: false,
      approvals_version: "v2",
    });
    expect(
      await waitForSessionIdle("versioned", () => true, jest.fn()),
    ).toEqual({ kind: "idle", stale: true, backgroundWork: false });
  });

  // A reply can start and finish between two status reads.
  it("reports a newer response that the chat does not show", async () => {
    const shown: Message = {
      nodeId: 2,
      messageId: 2,
      parentNodeId: null,
      type: "assistant",
      message: "",
      files: [],
      packets: [],
    };
    useChatSessionStore
      .getState()
      .hydrateSession("latest", new Map([[2, shown]]), "v1");
    const status = jest.mocked(getChatSessionStatus);
    status.mockResolvedValueOnce({
      is_processing: false,
      approvals_version: "v1",
      latest_response_id: 2,
    });
    expect(await waitForSessionIdle("latest", () => true, jest.fn())).toEqual({
      kind: "idle",
      stale: false,
      backgroundWork: false,
    });

    status.mockResolvedValueOnce({
      is_processing: false,
      approvals_version: "v1",
      latest_response_id: 4,
    });
    expect(await waitForSessionIdle("latest", () => true, jest.fn())).toEqual({
      kind: "idle",
      stale: true,
      backgroundWork: false,
    });
  });

  // A finished agent's unread result starts the root's turn after the read.
  it.each([{ has_active_subagents: true }, { has_startable_input: true }])(
    "reports background work for %o",
    async (work) => {
      useChatSessionStore.getState().hydrateSession("work", new Map(), "v1");
      jest.mocked(getChatSessionStatus).mockResolvedValueOnce({
        is_processing: false,
        approvals_version: "v1",
        ...work,
      });
      expect(await waitForSessionIdle("work", () => true, jest.fn())).toEqual({
        kind: "idle",
        stale: false,
        backgroundWork: true,
      });
    },
  );
});

it.each([401, 403, 404])(
  "stops polling a permanent %s failure without declaring idle",
  async (status) => {
    jest.useFakeTimers();
    const error = new ApiError({ status, detail: "Conversation unavailable" });
    jest.mocked(getChatSessionStatus).mockRejectedValue(error);
    await expect(waitForSessionIdle("s", () => true, jest.fn())).rejects.toBe(
      error,
    );
    expect(getChatSessionStatus).toHaveBeenCalledTimes(1);
    expect(jest.getTimerCount()).toBe(0);
  },
);
