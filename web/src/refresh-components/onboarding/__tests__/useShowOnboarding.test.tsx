import React from "react";
import { renderHook, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useShowOnboarding } from "@/hooks/useShowOnboarding";
import { OnboardingStep } from "../types";

// Mock useOnboardingState to isolate useShowOnboarding logic
const mockActions = {
  nextStep: jest.fn(),
  prevStep: jest.fn(),
  goToStep: jest.fn(),
  setButtonActive: jest.fn(),
  updateName: jest.fn(),
  updateData: jest.fn(),
  setLoading: jest.fn(),
  setError: jest.fn(),
  reset: jest.fn(),
};

let mockStepIndex = 0;

jest.mock("@/refresh-components/onboarding/useOnboardingState", () => ({
  useOnboardingState: () => ({
    state: {
      currentStep: OnboardingStep.Welcome,
      stepIndex: mockStepIndex,
      totalSteps: 3,
      data: {},
      isButtonActive: true,
      isLoading: false,
    },
    llmDescriptors: [],
    actions: mockActions,
    isLoading: false,
  }),
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
  const defaultParams = {
    liveAssistant: undefined,
    isLoadingProviders: false,
    hasAnyProvider: false,
    isLoadingChatSessions: false,
    chatSessionsCount: 0,
    userId: "user-1",
    ...overrides,
  };

  return renderHook((props) => useShowOnboarding(props), {
    initialProps: defaultParams,
  });
}

describe("useShowOnboarding", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockStepIndex = 0;
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

    // Re-render with same userId but provider data now available
    rerender({
      liveAssistant: undefined,
      isLoadingProviders: false,
      hasAnyProvider: true,
      isLoadingChatSessions: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });

    // Should correct to false — providers exist, no need for LLM setup flow
    expect(result.current.showOnboarding).toBe(false);
  });

  it("does not self-correct when user has advanced past Welcome step", () => {
    const { result, rerender } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });
    expect(result.current.showOnboarding).toBe(true);

    // Simulate user advancing past Welcome (e.g. they configured an LLM provider)
    mockStepIndex = 1;

    // Re-render with same userId but provider data now available
    rerender({
      liveAssistant: undefined,
      isLoadingProviders: false,
      hasAnyProvider: true,
      isLoadingChatSessions: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });

    // Should stay true — user is actively using onboarding
    expect(result.current.showOnboarding).toBe(true);
  });

  it("re-evaluates when userId changes", () => {
    const { result, rerender } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });
    expect(result.current.showOnboarding).toBe(true);

    // Change to a new userId with providers available
    rerender({
      liveAssistant: undefined,
      isLoadingProviders: false,
      hasAnyProvider: true,
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

  it("returns onboardingState and actions from useOnboardingState", () => {
    const { result } = renderUseShowOnboarding();
    expect(result.current.onboardingState.currentStep).toBe(
      OnboardingStep.Welcome
    );
    expect(result.current.onboardingActions).toBeDefined();
    expect(result.current.llmDescriptors).toEqual([]);
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
