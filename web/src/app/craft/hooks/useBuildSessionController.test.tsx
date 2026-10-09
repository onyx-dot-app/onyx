/**
 * @jest-environment jsdom
 */
import { act, renderHook, waitFor } from "@tests/setup/test-utils";
import { useBuildSessionController } from "@/app/craft/hooks/useBuildSessionController";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));
jest.mock("@/app/craft/hooks/usePreProvisionPolling", () => ({
  usePreProvisionPolling: jest.fn(),
}));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLanguageModels: () => ({ llmProviders: [] }),
}));
jest.mock("@/app/craft/onboarding/constants", () => ({
  hasSupportedCraftProvider: () => true,
}));
jest.mock("@/app/craft/services/apiServices");

const SESSION_ID = "55fa40e0-777e-4fd3-9a0d-cf05dfb616dc";

describe("useBuildSessionController", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.mocked(api.fetchOutputInventory).mockResolvedValue({
      files: [],
      complete: true,
    });
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
      controllerState: {
        lastTriggeredForUrl: null,
        loadedSessionId: SESSION_ID,
      },
      preProvisioning: { status: "idle" },
    } as never);
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      isLoaded: true,
      skillsStale: false,
    });
    useBuildSessionStore.getState().setCurrentSession(SESSION_ID);
  });

  it("refreshes cached file revisions on entry without opening new outputs", async () => {
    const store = () => useBuildSessionStore.getState();
    store().updateSessionData(SESSION_ID, {
      status: "active",
      outputInventory: {
        "outputs/deck.pptx": {
          path: "outputs/deck.pptx",
          revision: "old",
          size: 100,
        },
      },
    });
    jest.mocked(api.fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [
        { path: "outputs/deck.pptx", revision: "updated", size: 100 },
        { path: "outputs/other.pdf", revision: "new", size: 100 },
      ],
    });

    renderHook(() =>
      useBuildSessionController({ existingSessionId: SESSION_ID })
    );
    await waitFor(() => {
      expect(store().sessions.get(SESSION_ID)).toMatchObject({
        outputInventory: {
          "outputs/deck.pptx": {
            path: "outputs/deck.pptx",
            revision: "updated",
            size: 100,
          },
          "outputs/other.pdf": {
            path: "outputs/other.pdf",
            revision: "new",
            size: 100,
          },
        },
        panelTabs: [],
        outputPanelOpen: false,
        filesNeedsRefresh: 1,
      });
    });
  });

  it("does not absorb live outputs on entry or focus during a running turn", async () => {
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      status: "running",
      activeTurnId: "live-turn",
      outputInventory: {},
    });
    renderHook(() =>
      useBuildSessionController({ existingSessionId: SESSION_ID })
    );
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(api.fetchOutputInventory).not.toHaveBeenCalled();
  });

  it("marks skills stale from reads without clearing confirmed stale state", async () => {
    jest.mocked(api.fetchSession).mockResolvedValue({
      skills_stale: true,
    } as never);

    renderHook(() =>
      useBuildSessionController({ existingSessionId: SESSION_ID })
    );

    await waitFor(() => {
      expect(api.fetchSession).toHaveBeenCalledWith(SESSION_ID, {
        checkWorkspace: false,
      });
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(true);
    });

    jest.mocked(api.fetchSession).mockResolvedValue({
      skills_stale: false,
    } as never);
    act(() => window.dispatchEvent(new Event("focus")));

    await waitFor(() => {
      expect(api.fetchSession).toHaveBeenCalledTimes(2);
    });
    await act(async () => Promise.resolve());
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(true);
  });

  it("does not restore stale state after an intervening reload", async () => {
    let resolveRefresh:
      | ((value: { skills_stale: boolean }) => void)
      | undefined;
    jest.mocked(api.fetchSession).mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }) as never
    );

    renderHook(() =>
      useBuildSessionController({ existingSessionId: SESSION_ID })
    );
    await waitFor(() => expect(api.fetchSession).toHaveBeenCalled());

    await act(async () => {
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        skillsStale: true,
      });
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        skillsStale: false,
      });
      resolveRefresh?.({ skills_stale: true });
      await Promise.resolve();
    });

    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(false);
  });

  it("applies stale state after an unrelated session update", async () => {
    let resolveRefresh:
      | ((value: { skills_stale: boolean }) => void)
      | undefined;
    jest.mocked(api.fetchSession).mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }) as never
    );

    renderHook(() =>
      useBuildSessionController({ existingSessionId: SESSION_ID })
    );
    await waitFor(() => expect(api.fetchSession).toHaveBeenCalled());

    await act(async () => {
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        status: "running",
      });
      resolveRefresh?.({ skills_stale: true });
      await Promise.resolve();
    });

    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(true);
  });

  it("ignores a late validity response after the first message claims the sandbox", async () => {
    const store = () => useBuildSessionStore.getState();
    store().setCurrentSession(null);
    useBuildSessionStore.setState({
      preProvisioning: { status: "ready", sessionId: SESSION_ID },
      controllerState: {
        lastTriggeredForUrl: "new-build",
        loadedSessionId: null,
      },
    });
    let resolveCheck:
      | ((
          value: Awaited<ReturnType<typeof api.checkPreProvisionedSession>>
        ) => void)
      | undefined;
    jest.mocked(api.checkPreProvisionedSession).mockReturnValue(
      new Promise((resolve) => {
        resolveCheck = resolve;
      })
    );
    renderHook(() => useBuildSessionController({ existingSessionId: null }));

    act(() => window.dispatchEvent(new Event("focus")));
    expect(api.checkPreProvisionedSession).toHaveBeenCalledWith(SESSION_ID);
    await act(async () => {
      await store().consumePreProvisionedSession();
      resolveCheck?.({ valid: false, session_id: SESSION_ID });
    });

    expect(store().preProvisioning).toEqual({
      status: "starting",
      sessionId: SESSION_ID,
    });
    expect(api.createSession).not.toHaveBeenCalled();
  });
});
