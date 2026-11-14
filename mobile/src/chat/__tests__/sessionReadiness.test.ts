import { afterEach, describe, expect, it, jest } from "@jest/globals";
import { ApiError } from "@/api/errors";
import { getChatSessionStatus } from "@/api/chat/sessions";
import { waitForSessionIdle } from "@/chat/sessionReadiness";

jest.mock("@/api/chat/sessions", () => ({ getChatSessionStatus: jest.fn() }));
afterEach(() => {
  jest.useRealTimers();
  jest.resetAllMocks();
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
        current_stream: { stream_id: 7 },
      })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 8 },
      });
    const pending = waitForSessionIdle(
      "s",
      () => true,
      jest.fn(),
      (streamId) => streamId !== 7,
    );
    await jest.advanceTimersByTimeAsync(2000);
    expect(await pending).toEqual({ kind: "stream", streamId: 8 });
    expect(getChatSessionStatus).toHaveBeenCalledTimes(3);
  });
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
