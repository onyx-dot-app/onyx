/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";
import { useWakeOnIntent } from "@/app/craft/hooks/useWakeOnIntent";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { ApiSandboxResponse } from "@/app/craft/types/streamingTypes";

const SESSION_ID = "11111111-1111-1111-1111-111111111111";

function sandbox(
  overrides: Partial<ApiSandboxResponse> = {}
): ApiSandboxResponse {
  return {
    id: "sb1",
    status: "sleeping",
    container_id: null,
    created_at: "2026-07-01T00:00:00.000Z",
    last_heartbeat: "2026-07-01T00:00:00.000Z",
    nextjs_port: null,
    ...overrides,
  };
}

describe("useWakeOnIntent", () => {
  let loadSession: jest.Mock;

  beforeEach(() => {
    loadSession = jest.fn();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
      loadSession,
    } as never);
  });

  function seedSession(sandboxState: ApiSandboxResponse): void {
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      status: "running",
      sandbox: sandboxState,
    });
    useBuildSessionStore.getState().setCurrentSession(SESSION_ID);
  }

  it("wakes the sandbox when sleeping", () => {
    seedSession(sandbox({ status: "sleeping" }));
    const { result } = renderHook(() => useWakeOnIntent());

    result.current();

    expect(loadSession).toHaveBeenCalledTimes(1);
    expect(loadSession).toHaveBeenCalledWith(SESSION_ID, { force: true });
  });

  it("wakes on terminated but not running, restoring, or failed", () => {
    const { result } = renderHook(() => useWakeOnIntent());

    seedSession(sandbox({ status: "terminated" }));
    result.current();
    expect(loadSession).toHaveBeenCalledTimes(1);

    loadSession.mockClear();
    seedSession(sandbox({ status: "running" }));
    result.current();
    expect(loadSession).not.toHaveBeenCalled();

    seedSession(sandbox({ status: "restoring" }));
    result.current();
    expect(loadSession).not.toHaveBeenCalled();

    seedSession(sandbox({ status: "failed" }));
    result.current();
    expect(loadSession).not.toHaveBeenCalled();
  });

  it("single-flights rapid intent calls while still sleeping", () => {
    seedSession(sandbox({ status: "sleeping" }));
    const { result } = renderHook(() => useWakeOnIntent());

    result.current();
    result.current();

    expect(loadSession).toHaveBeenCalledTimes(1);
  });

  it("wakes again after status returns to running then sleeps again", () => {
    seedSession(sandbox({ status: "sleeping" }));
    const { result } = renderHook(() => useWakeOnIntent());

    result.current();
    expect(loadSession).toHaveBeenCalledTimes(1);

    seedSession(sandbox({ status: "running" }));
    result.current();
    expect(loadSession).toHaveBeenCalledTimes(1);

    seedSession(sandbox({ status: "sleeping" }));
    result.current();
    expect(loadSession).toHaveBeenCalledTimes(2);
  });
});
