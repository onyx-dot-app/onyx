/**
 * @jest-environment jsdom
 */
import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useSandboxStatusReconciler } from "@/app/craft/hooks/useSandboxStatusReconciler";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";
import type { SandboxRuntimeState } from "@/app/craft/types/streamingTypes";

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

function sandbox(
  overrides: Partial<SandboxRuntimeState> = {}
): SandboxRuntimeState {
  return {
    id: "sb1",
    status: "running",
    container_id: null,
    created_at: "2026-07-01T00:00:00.000Z",
    last_heartbeat: "2026-07-01T00:00:00.000Z",
    ...overrides,
  };
}

function seedSession(sandboxState: SandboxRuntimeState): void {
  useBuildSessionStore.getState().createSession(SESSION_ID, {
    status: "running",
    sandbox: sandboxState,
  });
  useBuildSessionStore.getState().setCurrentSession(SESSION_ID);
}

describe("useSandboxStatusReconciler", () => {
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

  it.each(["sleeping", "terminated", "failed"] as const)(
    "updates the runtime state when the API reports %s",
    async (status) => {
      seedSession(sandbox());
      mockedApi.fetchSandboxStatus.mockResolvedValue({ status });

      renderHook(() => useSandboxStatusReconciler(), { wrapper });

      await waitFor(() => {
        const session = useBuildSessionStore
          .getState()
          .sessions.get(SESSION_ID);
        expect(session?.sandbox?.status).toBe(status);
      });
    }
  );

  it("does not poll an inactive sandbox", async () => {
    seedSession(sandbox({ status: "sleeping" }));

    renderHook(() => useSandboxStatusReconciler(), { wrapper });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mockedApi.fetchSandboxStatus).not.toHaveBeenCalled();
  });

  it("keeps polling while the sandbox is provisioning", async () => {
    seedSession(sandbox({ status: "provisioning" }));
    mockedApi.fetchSandboxStatus.mockResolvedValue({ status: "provisioning" });

    renderHook(() => useSandboxStatusReconciler(), { wrapper });

    await waitFor(() => {
      expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);
    });
    expect(loadSession).not.toHaveBeenCalled();
  });

  it("reconciles the workspace when provisioning finishes", async () => {
    seedSession(sandbox({ status: "provisioning" }));
    mockedApi.fetchSandboxStatus.mockResolvedValue({ status: "running" });

    renderHook(() => useSandboxStatusReconciler(), { wrapper });

    await waitFor(() => {
      expect(loadSession).toHaveBeenCalledWith(SESSION_ID, { force: true });
    });
  });

  it("does not let a late poll overwrite workspace restoration", async () => {
    seedSession(sandbox({ status: "provisioning" }));
    let finishPoll: (value: { status: "running" }) => void = () => {};
    mockedApi.fetchSandboxStatus.mockReturnValue(
      new Promise((resolve) => {
        finishPoll = resolve;
      })
    );

    renderHook(() => useSandboxStatusReconciler(), { wrapper });

    await waitFor(() => {
      expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);
    });
    act(() => {
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        sandbox: sandbox({ status: "restoring" }),
      });
      finishPoll({ status: "running" });
    });

    await waitFor(() => {
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("restoring");
    });
    expect(loadSession).not.toHaveBeenCalled();
  });

  it("stops polling after the sandbox becomes inactive", async () => {
    seedSession(sandbox());
    mockedApi.fetchSandboxStatus.mockResolvedValue({ status: "sleeping" });

    renderHook(() => useSandboxStatusReconciler(), { wrapper });

    await waitFor(() => {
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("sleeping");
    });
    expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mockedApi.fetchSandboxStatus).toHaveBeenCalledTimes(1);
  });

  it("leaves an unchanged runtime status alone", async () => {
    seedSession(sandbox());
    mockedApi.fetchSandboxStatus.mockResolvedValue({ status: "running" });

    renderHook(() => useSandboxStatusReconciler(), { wrapper });

    await waitFor(() => {
      expect(mockedApi.fetchSandboxStatus).toHaveBeenCalled();
    });
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.sandbox?.status
    ).toBe("running");
  });
});
