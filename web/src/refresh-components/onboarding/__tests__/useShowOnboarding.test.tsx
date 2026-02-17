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

jest.mock("@/refresh-components/onboarding/useOnboardingState", () => ({
  useOnboardingState: () => ({
    state: {
      currentStep: OnboardingStep.Welcome,
      stepIndex: 0,
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

  it("only evaluates once per userId", () => {
    const { result, rerender } = renderUseShowOnboarding({
      hasAnyProvider: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });
    expect(result.current.showOnboarding).toBe(true);

    // Re-render with same userId but different provider state
    rerender({
      liveAssistant: undefined,
      isLoadingProviders: false,
      hasAnyProvider: true,
      isLoadingChatSessions: false,
      chatSessionsCount: 0,
      userId: "user-1",
    });

    // Should still be true because it was already evaluated for this userId
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
});
