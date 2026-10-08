import { waitForChatSessionIdle } from "@/lib/chat/sessionReadiness";

function sessionResponse(
  isProcessing: boolean,
  streamId: number | null = null
) {
  return {
    ok: true,
    json: async () => ({
      is_processing: isProcessing,
      current_stream: streamId === null ? null : { stream_id: streamId },
    }),
  } as Response;
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

test("waits through setup, generation, and storage before releasing all callers", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(sessionResponse(true))
    .mockResolvedValueOnce(sessionResponse(true, 42))
    .mockResolvedValueOnce(sessionResponse(false));
  const check = waitForChatSessionIdle("session");
  expect(waitForChatSessionIdle("session")).toBe(check);
  const completed = jest.fn();
  void check.then(completed);

  await jest.advanceTimersByTimeAsync(1000);
  expect(completed).not.toHaveBeenCalled();
  await jest.advanceTimersByTimeAsync(1000);
  await check;
  expect(completed).toHaveBeenCalledTimes(1);
  expect(fetchSpy).toHaveBeenCalledTimes(3);
});

test("a failed status request never reports idle and can be retried", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce({ ok: false, status: 503 } as Response)
    .mockResolvedValueOnce(sessionResponse(false));
  await expect(waitForChatSessionIdle("failed-session")).rejects.toThrow("503");
  await expect(
    waitForChatSessionIdle("failed-session")
  ).resolves.toBeUndefined();
  expect(fetchSpy).toHaveBeenCalledTimes(2);
});

test("healthy long-running work stays busy beyond two minutes", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(sessionResponse(true));
  const completed = jest.fn();
  const check = waitForChatSessionIdle("research-session");
  void check.then(completed);
  await jest.advanceTimersByTimeAsync(180_000);
  expect(completed).not.toHaveBeenCalled();
  fetchSpy.mockResolvedValue(sessionResponse(false));
  await jest.advanceTimersByTimeAsync(1000);
  await check;
  expect(completed).toHaveBeenCalledTimes(1);
});
