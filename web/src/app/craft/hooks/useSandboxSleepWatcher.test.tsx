/**
 * @jest-environment jsdom
 */
import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useSandboxSleepWatcher } from "@/app/craft/hooks/useSandboxSleepWatcher";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";
import { ApiSandboxResponse } from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices");

const mockedApi = api as jest.Mocked<typeof api>;

const SESSION_ID = "11111111-1111-1111-1111-111111111111";

function wrapper({ children }: { children: React.ReactNode }) {
  return React.createElement(
    SWRConfig,
    { value: { provider: () => new Map(), dedupingInterval: 0 } },
    children
  );
}

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
    ...overrides,
  };
}

function seedSession(sandbox: ApiSandboxResponse): void {
  useBuildSessionStore.getState().createSession(SESSION_ID, {
    status: "running",
    sandbox,
  });
  useBuildSessionStore.getState().setCurrentSession(SESSION_ID);
}

describe("useSandboxSleepWatcher", () => {
  let loadSession: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    loadSession = jest.fn().mockResolvedValue(undefined);
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
      loadSession,
    } as never);
  });

  it("flips the sandbox to sleeping when the poll reports sleeping", async () => {
    seedSession(runningSandbox());
    mockedApi.fetchSandboxStatus.mockResolvedValue({
      status: "sleeping",
    });

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await waitFor(() => {
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("sleeping");
    });
  });

  it("flips the sandbox to terminated when the poll reports terminated", async () => {
    seedSession(runningSandbox());
    mockedApi.fetchSandboxStatus.mockResolvedValue({
      status: "terminated",
    });

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await waitFor(() => {
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("terminated");
    });
  });

  it("never polls when the sandbox is not active or provisioning", async () => {
    seedSession(runningSandbox({ status: "sleeping" }));

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mockedApi.fetchSandboxStatus).not.toHaveBeenCalled();
  });

  it("keeps polling while the sandbox is provisioning", async () => {
    seedSession(runningSandbox({ status: "provisioning" }));
    mockedApi.fetchSandboxStatus.mockResolvedValue({
      status: "provisioning",
    });

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await waitFor(() => {
      expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);
    });
    expect(loadSession).not.toHaveBeenCalled();
  });

  it("reconciles the session workspace when provisioning finishes", async () => {
    seedSession(runningSandbox({ status: "provisioning" }));
    mockedApi.fetchSandboxStatus.mockResolvedValue({
      status: "running",
    });

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await waitFor(() => {
      expect(loadSession).toHaveBeenCalledWith(SESSION_ID, { force: true });
    });
  });

  it("does not let a late poll overwrite workspace restoration", async () => {
    seedSession(runningSandbox({ status: "provisioning" }));
    let finishPoll: (value: { status: "running" }) => void = () => {};
    mockedApi.fetchSandboxStatus.mockReturnValue(
      new Promise((resolve) => {
        finishPoll = resolve;
      })
    );

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await waitFor(() => {
      expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);
    });
    act(() => {
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        sandbox: runningSandbox({ status: "restoring" }),
      });
      finishPoll({ status: "running" });
    });

    await waitFor(() => {
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("restoring");
    });
    expect(loadSession).not.toHaveBeenCalled();
  });

  it("stops polling once the sandbox is asleep", async () => {
    seedSession(runningSandbox());
    mockedApi.fetchSandboxStatus.mockResolvedValue({
      status: "sleeping",
    });

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await waitFor(() => {
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("sleeping");
    });

    expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);

    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);
  });

  it("leaves the sandbox running when the poll reports running", async () => {
    seedSession(runningSandbox());
    mockedApi.fetchSandboxStatus.mockResolvedValue({
      status: "running",
    });

    renderHook(() => useSandboxSleepWatcher(), { wrapper });

    await waitFor(() => {
      expect(mockedApi.fetchSandboxStatus).toHaveBeenCalled();
    });

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.sandbox?.status).toBe("running");
  });
});
