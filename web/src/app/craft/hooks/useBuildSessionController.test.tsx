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
  useLLMProviders: () => ({ llmProviders: [] }),
}));
jest.mock("@/app/craft/onboarding/constants", () => ({
  hasSupportedCraftProvider: () => true,
}));
jest.mock("@/app/craft/services/apiServices");

const SESSION_ID = "55fa40e0-777e-4fd3-9a0d-cf05dfb616dc";

describe("useBuildSessionController", () => {
  beforeEach(() => {
    jest.clearAllMocks();
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

  it("refreshes stale skill state on mount and browser focus", async () => {
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
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(false);
    });
  });

  it("does not overwrite a newer local stale-state change", async () => {
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      skillsStale: true,
    });
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
        skillsStale: false,
      });
      resolveRefresh?.({ skills_stale: true });
      await Promise.resolve();
    });

    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(false);
  });
});
