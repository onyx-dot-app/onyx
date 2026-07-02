/**
 * @jest-environment jsdom
 */
import { act, renderHook } from "@testing-library/react";
import {
  computeSleepDeadlineMs,
  RETRY_DELAY_MS,
  SLEEP_CHECK_SLACK_MS,
  useSandboxSleepWatcher,
} from "@/app/craft/hooks/useSandboxSleepWatcher";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";
import { ApiSandboxResponse } from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices");

const mockedApi = api as jest.Mocked<typeof api>;

const SESSION_ID = "11111111-1111-1111-1111-111111111111";

describe("computeSleepDeadlineMs", () => {
  it("falls back to now when both last_heartbeat and created_at are null", () => {
    const now = 1_000_000;
    expect(computeSleepDeadlineMs(null, null, 3600, now)).toBe(
      now + 3600 * 1000 + SLEEP_CHECK_SLACK_MS
    );
  });

  it("computes the deadline from a real heartbeat", () => {
    const heartbeat = "2026-07-01T00:00:00.000Z";
    const heartbeatMs = Date.parse(heartbeat);
    expect(
      computeSleepDeadlineMs(heartbeat, null, 3600, heartbeatMs + 1000)
    ).toBe(heartbeatMs + 3600 * 1000 + SLEEP_CHECK_SLACK_MS);
  });

  it("includes the reaper-sweep slack in the deadline", () => {
    const heartbeat = "2026-07-01T00:00:00.000Z";
    const heartbeatMs = Date.parse(heartbeat);
    const deadline = computeSleepDeadlineMs(heartbeat, null, 0, heartbeatMs);
    expect(deadline - heartbeatMs).toBe(SLEEP_CHECK_SLACK_MS);
  });

  it("falls back to created_at when last_heartbeat is null", () => {
    const createdAt = "2026-07-01T00:00:00.000Z";
    const createdAtMs = Date.parse(createdAt);
    expect(
      computeSleepDeadlineMs(null, createdAt, 3600, createdAtMs + 1000)
    ).toBe(createdAtMs + 3600 * 1000 + SLEEP_CHECK_SLACK_MS);
  });
});

function runningSandbox(
  overrides: Partial<ApiSandboxResponse> = {}
): ApiSandboxResponse {
  return {
    id: "sb1",
    status: "running",
    container_id: null,
    created_at: "2026-07-01T00:00:00.000Z",
    last_heartbeat: "2026-07-01T00:00:00.000Z",
    nextjs_port: null,
    idle_timeout_seconds: 0,
    ...overrides,
  };
}

describe("useSandboxSleepWatcher", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    } as never);
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  function seedSession(sandbox: ApiSandboxResponse): void {
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      status: "running",
      sandbox,
    });
    useBuildSessionStore.getState().setCurrentSession(SESSION_ID);
  }

  it("transitions the sandbox to sleeping once the reaper deadline passes", async () => {
    seedSession(runningSandbox());
    mockedApi.fetchSandboxStatus.mockResolvedValue({
      status: "sleeping",
      last_heartbeat: "2026-07-01T00:00:00.000Z",
      created_at: "2026-07-01T00:00:00.000Z",
      idle_timeout_seconds: 0,
    } as never);

    renderHook(() => useSandboxSleepWatcher());

    await act(async () => {
      jest.advanceTimersByTime(SLEEP_CHECK_SLACK_MS);
    });

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.sandbox?.status).toBe("sleeping");
  });

  it("retries once on transient failure then gives up", async () => {
    seedSession(runningSandbox());
    mockedApi.fetchSandboxStatus.mockRejectedValue(
      new Error("sandbox unreachable")
    );

    renderHook(() => useSandboxSleepWatcher());

    await act(async () => {
      jest.advanceTimersByTime(SLEEP_CHECK_SLACK_MS);
    });
    expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      jest.advanceTimersByTime(RETRY_DELAY_MS);
    });
    expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      jest.advanceTimersByTime(RETRY_DELAY_MS);
    });
    expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(2);
  });

  it("never polls when the sandbox is not running", async () => {
    seedSession(runningSandbox({ status: "sleeping" }));

    renderHook(() => useSandboxSleepWatcher());

    await act(async () => {
      jest.advanceTimersByTime(SLEEP_CHECK_SLACK_MS + RETRY_DELAY_MS * 5);
    });

    expect(mockedApi.fetchSandboxStatus).not.toHaveBeenCalled();
  });
});
