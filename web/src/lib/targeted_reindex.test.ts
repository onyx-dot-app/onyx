/** waitForTargetedReindexJobs polls each job until it ends and totals what the retry toast reports. */
import type { TargetedReindexJobStatus } from "@/lib/connectors/types";
import { waitForTargetedReindexJobs } from "@/lib/targeted_reindex";

function job(
  id: number,
  status: TargetedReindexJobStatus["status"],
  resolved = 0,
  stillFailing = 0
): TargetedReindexJobStatus {
  return {
    id,
    status,
    requested_at: "2026-10-22T00:00:00Z",
    completed_at: null,
    target_count: resolved + stillFailing,
    resolved_count: resolved,
    still_failing_count: stillFailing,
    skipped_count: 0,
    resolved_summary: [],
  };
}

function respond(body: TargetedReindexJobStatus | null): Response {
  return {
    ok: body !== null,
    json: async () => body,
  } as Response;
}

// Advances the poll sleeps until the wait settles.
async function settle<T>(promise: Promise<T>): Promise<T> {
  let done = false;
  let value: T | undefined;
  promise.then((v) => {
    done = true;
    value = v;
  });
  for (let i = 0; i < 20 && !done; i++) {
    await jest.advanceTimersByTimeAsync(2000);
  }
  expect(done).toBe(true);
  return value as T;
}

describe("waitForTargetedReindexJobs", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.useFakeTimers();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    jest.useRealTimers();
  });

  test("polls until every job ends and sums the counts", async () => {
    fetchSpy
      .mockResolvedValueOnce(respond(job(1, "in_progress")))
      .mockResolvedValueOnce(respond(job(2, "success", 3, 1)))
      .mockResolvedValueOnce(respond(job(1, "success", 2, 0)));

    const outcome = await settle(waitForTargetedReindexJobs([1, 2]));

    expect(outcome).toEqual({ finished: true, resolved: 5, still_failing: 1 });
    // The ended job is not read again.
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  test("a failed job means the retry did not finish", async () => {
    fetchSpy.mockResolvedValueOnce(respond(job(1, "failed")));

    const outcome = await settle(waitForTargetedReindexJobs([1]));

    expect(outcome.finished).toBe(false);
  });

  test("a failed read is retried on the next poll", async () => {
    fetchSpy
      .mockResolvedValueOnce(respond(null))
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(respond(job(1, "success", 1, 0)));

    const outcome = await settle(waitForTargetedReindexJobs([1]));

    expect(outcome).toEqual({ finished: true, resolved: 1, still_failing: 0 });
  });

  test("a missing job stops the wait without finishing", async () => {
    fetchSpy.mockResolvedValueOnce({ ok: false, status: 404 } as Response);

    const outcome = await settle(waitForTargetedReindexJobs([1]));

    expect(outcome.finished).toBe(false);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  test("a stalled read is aborted and retried", async () => {
    fetchSpy
      .mockImplementationOnce(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new Error("aborted"))
            );
          })
      )
      .mockResolvedValueOnce(respond(job(1, "success", 1, 0)));

    const outcome = await settle(waitForTargetedReindexJobs([1]));

    expect(outcome).toEqual({ finished: true, resolved: 1, still_failing: 0 });
  });

  test("a job that never ends stops at the wait limit", async () => {
    fetchSpy.mockResolvedValue(respond(job(1, "in_progress")));

    const wait = waitForTargetedReindexJobs([1]);
    await jest.advanceTimersByTimeAsync(60 * 60 * 1000 + 2000);

    expect((await wait).finished).toBe(false);
  });
});
