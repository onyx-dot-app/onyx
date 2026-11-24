import React from "react";
import { renderHook, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useShowOnboarding } from "@/lib/onboarding/hooks";
import { OnboardingStep } from "@/lib/onboarding/types";
import { updateUserPersonalization } from "@/lib/users/svc";

interface MockUser {
  id: string;
  personalization: { name: string; preferred_name: string };
}

// Mock underlying dependencies used by the inlined useOnboardingState
let mockUser: MockUser | null = null;
const mockRefreshUser = jest.fn<Promise<void>, []>();
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: mockUser,
    refreshUser: mockRefreshUser,
  }),
}));

// Configurable mock for useProviderStatus
const mockProviderStatus = {
  llmProviders: [] as unknown[],
  isLoadingProviders: false,
  hasProviders: false,
  refreshProviderInfo: jest.fn(),
};

jest.mock("@/components/chat/ProviderContext", () => ({
  useProviderStatus: () => mockProviderStatus,
}));

jest.mock("@/lib/languageModels/hooks", () => ({
  useLanguageModelsForAgent: () => ({
    refetch: jest.fn(),
  }),
}));

jest.mock("@/lib/users/svc", () => ({
  ...jest.requireActual("@/lib/users/svc"),
  updateUserPersonalization: jest.fn(),
}));

function renderUseShowOnboarding(
  overrides: {
    isLoadingProviders?: boolean;
    hasAnyProvider?: boolean;
    isLoadingChatSessions?: boolean;
    chatSessionsCount?: number;
    userId?: string;
  } = {}
) {
  // Configure the provider mock based on overrides
  mockProviderStatus.isLoadingProviders = overrides.isLoadingProviders ?? false;
  mockProviderStatus.hasProviders = overrides.hasAnyProvider ?? false;
  mockProviderStatus.llmProviders = overrides.hasAnyProvider
    ? [{ provider: "openai" }]
    : [];

  const defaultParams = {
    activeAgent: undefined as undefined,
    isLoadingChatSessions: overrides.isLoadingChatSessions ?? false,
    chatSessionsCount: overrides.chatSessionsCount ?? 0,
    userId: "userId" in overrides ? overrides.userId : "user-1",
  };

  return renderHook((props) => useShowOnboarding(props), {
    initialProps: defaultParams,
  });
}

describe("useShowOnboarding", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockUser = null;
    // Reset mock to defaults
    mockProviderStatus.llmProviders = [];
    mockProviderStatus.isLoadingProviders = false;
    mockProviderStatus.hasProviders = false;
  });

  it("returns showOnboarding=false while providers are loading", () => {
    const { result } = renderUseShowOnboarding({
      isLoadingProviders: true,
    });
    expect(result.current.showOnboarding).toBe(false);
  });

  it("returns showOnboarding=false while chat sessions are loading", () => {
    const { result } = renderUseShowOnboarding({
      isLoadingChatSessions: true,
    });
    expect(result.current.showOnboarding).toBe(false);
  });

  it("returns showOnboarding=false when userId is undefined", () => {
    const { result } = renderUseShowOnboarding({
      userId: undefined,
    });
    expect(result.current.showOnboarding).toBe(false);
  });

  it("returns showOnboarding=true when no providers and no chat sessions", () => {
    const { result } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
    });
    expect(result.current.showOnboarding).toBe(true);
  });

  it("returns showOnboarding=false when providers exist", () => {
    const { result } = renderUseShowOnboarding({
      hasAnyProvider: true,
      chatSessionsCount: 0,
    });
    expect(result.current.showOnboarding).toBe(false);
  });

  it("returns showOnboarding=false when chatSessionsCount > 0", () => {
    const { result } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 5,
    });
    expect(result.current.showOnboarding).toBe(false);
  });

  it("self-corrects showOnboarding to false when providers arrive late", () => {
    const { result, rerender } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });
    expect(result.current.showOnboarding).toBe(true);

    // Simulate providers arriving — update the mock
    mockProviderStatus.hasProviders = true;
    mockProviderStatus.llmProviders = [{ provider: "openai" }];

    rerender({
      activeAgent: undefined,
      isLoadingChatSessions: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });

    // Should correct to false — providers exist, no need for LLM setup flow
    expect(result.current.showOnboarding).toBe(false);
  });

  it("re-evaluates when userId changes", () => {
    const { result, rerender } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });
    expect(result.current.showOnboarding).toBe(true);

    // Change to a new userId with providers available — update the mock
    mockProviderStatus.hasProviders = true;
    mockProviderStatus.llmProviders = [{ provider: "openai" }];

    rerender({
      activeAgent: undefined,
      isLoadingChatSessions: false,
      chatSessionsCount: 0,
      userId: "user-2",
    });

    expect(result.current.showOnboarding).toBe(false);
  });

  it("hideOnboarding sets showOnboarding to false", () => {
    const { result } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
    });
    expect(result.current.showOnboarding).toBe(true);

    act(() => {
      result.current.hideOnboarding();
    });

    expect(result.current.showOnboarding).toBe(false);
  });

  it("finishOnboarding sets showOnboarding to false", () => {
    const { result } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
    });
    expect(result.current.showOnboarding).toBe(true);

    act(() => {
      result.current.finishOnboarding();
    });

    expect(result.current.showOnboarding).toBe(false);
  });

  it("returns onboardingState and actions", () => {
    const { result } = renderUseShowOnboarding();
    expect(result.current.onboardingState.currentStep).toBe(
      OnboardingStep.PreStep
    );
    expect(result.current.onboardingActions).toBeDefined();
  });

  it("keeps filling the full name after the first save gives the user one", async () => {
    jest.useFakeTimers();
    try {
      mockUser = {
        id: "user-1",
        personalization: { name: "", preferred_name: "" },
      };
      const save = jest
        .mocked(updateUserPersonalization)
        .mockResolvedValue({ ok: true } as Response);
      // The refresh returns the name that the first save stored.
      mockRefreshUser.mockImplementation(async () => {
        mockUser = {
          id: "user-1",
          personalization: { name: "Jo", preferred_name: "Jo" },
        };
      });
      const { result, rerender } = renderUseShowOnboarding();

      act(() => result.current.onboardingActions.updateName("Jo"));
      await act(async () => {
        await jest.advanceTimersByTimeAsync(500);
      });
      expect(mockRefreshUser).toHaveBeenCalledTimes(1);
      rerender({
        activeAgent: undefined,
        isLoadingChatSessions: false,
        chatSessionsCount: 0,
        userId: "user-1",
      });

      act(() => result.current.onboardingActions.updateName("John Smith"));
      await act(async () => {
        await jest.advanceTimersByTimeAsync(500);
      });
      expect(save).toHaveBeenLastCalledWith({
        preferred_name: "John Smith",
        name: "John Smith",
      });
    } finally {
      jest.useRealTimers();
    }
  });

  describe("localStorage persistence", () => {
    it("finishOnboarding sets localStorage flag and onboardingDismissed", () => {
      const { result } = renderUseShowOnboarding({
        hasAnyProvider: false,
        chatSessionsCount: 0,
      });
      expect(result.current.showOnboarding).toBe(true);
      expect(result.current.onboardingDismissed).toBe(false);

      act(() => {
        result.current.finishOnboarding();
      });

      expect(result.current.showOnboarding).toBe(false);
      expect(result.current.onboardingDismissed).toBe(true);
      expect(localStorage.getItem("onyx:onboardingCompleted:user-1")).toBe(
        "true"
      );
    });

    it("hideOnboarding sets localStorage flag and onboardingDismissed", () => {
      const { result } = renderUseShowOnboarding({
        hasAnyProvider: false,
        chatSessionsCount: 0,
      });

      act(() => {
        result.current.hideOnboarding();
      });

      expect(result.current.onboardingDismissed).toBe(true);
      expect(localStorage.getItem("onyx:onboardingCompleted:user-1")).toBe(
        "true"
      );
    });

    it("showOnboarding stays false when localStorage flag is set", () => {
      localStorage.setItem("onyx:onboardingCompleted:user-1", "true");

      const { result } = renderUseShowOnboarding({
        hasAnyProvider: false,
        chatSessionsCount: 0,
      });

      expect(result.current.showOnboarding).toBe(false);
      expect(result.current.onboardingDismissed).toBe(true);
    });

    it("onboardingDismissed is false when localStorage flag is not set", () => {
      const { result } = renderUseShowOnboarding();
      expect(result.current.onboardingDismissed).toBe(false);
    });

    it("dismissal for user-1 does not suppress onboarding for user-2", () => {
      const { result: result1 } = renderUseShowOnboarding({
        hasAnyProvider: false,
        chatSessionsCount: 0,
        userId: "1",
      });
      expect(result1.current.showOnboarding).toBe(true);

      act(() => {
        result1.current.finishOnboarding();
      });
      expect(result1.current.onboardingDismissed).toBe(true);
      expect(localStorage.getItem("onyx:onboardingCompleted:1")).toBe("true");

      // user-2 should still see onboarding
      const { result: result2 } = renderUseShowOnboarding({
        hasAnyProvider: false,
        chatSessionsCount: 0,
        userId: "2",
      });
      expect(result2.current.showOnboarding).toBe(true);
      expect(result2.current.onboardingDismissed).toBe(false);
      expect(localStorage.getItem("onyx:onboardingCompleted:2")).toBeNull();
    });
  });
});

describe("useShowOnboarding isOnboardingResolved", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockUser = null;
    mockProviderStatus.llmProviders = [];
    mockProviderStatus.isLoadingProviders = false;
    mockProviderStatus.hasProviders = false;
  });

  it("is false while the user is loading", () => {
    const { result } = renderUseShowOnboarding({ userId: undefined });
    expect(result.current.isOnboardingResolved).toBe(false);
  });

  it("is false while providers are loading", () => {
    const { result } = renderUseShowOnboarding({ isLoadingProviders: true });
    expect(result.current.isOnboardingResolved).toBe(false);
  });

  it("is false while chat sessions are loading", () => {
    const { result } = renderUseShowOnboarding({
      isLoadingChatSessions: true,
    });
    expect(result.current.isOnboardingResolved).toBe(false);
  });

  it("is true with the final decision once everything has loaded", () => {
    const { result, rerender } = renderUseShowOnboarding({
      isLoadingChatSessions: true,
    });
    expect(result.current.isOnboardingResolved).toBe(false);

    rerender({
      activeAgent: undefined,
      isLoadingChatSessions: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });

    expect(result.current.isOnboardingResolved).toBe(true);
    expect(result.current.showOnboarding).toBe(true);
  });

  it("is true with dismissed set in the same render when dismissed in storage", () => {
    localStorage.setItem("onyx:onboardingCompleted:user-1", "true");

    const { result } = renderUseShowOnboarding({ isLoadingProviders: true });

    expect(result.current.isOnboardingResolved).toBe(true);
    expect(result.current.onboardingDismissed).toBe(true);
    expect(result.current.showOnboarding).toBe(false);
  });

  it("is false again for a new user until that user is evaluated", () => {
    const { result, rerender } = renderUseShowOnboarding();
    expect(result.current.isOnboardingResolved).toBe(true);

    rerender({
      activeAgent: undefined,
      isLoadingChatSessions: true,
      chatSessionsCount: 0,
      userId: "user-2",
    });

    expect(result.current.isOnboardingResolved).toBe(false);
  });
});
