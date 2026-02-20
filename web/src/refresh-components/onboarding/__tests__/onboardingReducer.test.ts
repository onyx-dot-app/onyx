import { onboardingReducer, initialState } from "../reducer";
import {
  OnboardingActionType,
  OnboardingStep,
  OnboardingState,
} from "../types";

describe("onboardingReducer", () => {
  describe("initial state", () => {
    it("starts at Welcome step with default values", () => {
      expect(initialState).toEqual({
        currentStep: OnboardingStep.Welcome,
        stepIndex: 0,
        totalSteps: 3,
        data: {},
        isButtonActive: true,
        isLoading: false,
      });
    });
  });

  describe("NEXT_STEP", () => {
    it("advances Welcome -> Name", () => {
      const result = onboardingReducer(initialState, {
        type: OnboardingActionType.NEXT_STEP,
      });
      expect(result.currentStep).toBe(OnboardingStep.Name);
      expect(result.stepIndex).toBe(1);
    });

    it("advances Name -> LlmSetup", () => {
      const state: OnboardingState = {
        ...initialState,
        currentStep: OnboardingStep.Name,
        stepIndex: 1,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.NEXT_STEP,
      });
      expect(result.currentStep).toBe(OnboardingStep.LlmSetup);
      expect(result.stepIndex).toBe(2);
    });

    it("advances LlmSetup -> Complete and sets isButtonActive to true", () => {
      const state: OnboardingState = {
        ...initialState,
        currentStep: OnboardingStep.LlmSetup,
        stepIndex: 2,
        isButtonActive: false,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.NEXT_STEP,
      });
      expect(result.currentStep).toBe(OnboardingStep.Complete);
      expect(result.stepIndex).toBe(3);
      expect(result.isButtonActive).toBe(true);
    });

    it("is a no-op when already at Complete", () => {
      const state: OnboardingState = {
        ...initialState,
        currentStep: OnboardingStep.Complete,
        stepIndex: 3,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.NEXT_STEP,
      });
      expect(result).toBe(state);
    });
  });

  describe("PREV_STEP", () => {
    it("goes Complete -> LlmSetup", () => {
      const state: OnboardingState = {
        ...initialState,
        currentStep: OnboardingStep.Complete,
        stepIndex: 3,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.PREV_STEP,
      });
      expect(result.currentStep).toBe(OnboardingStep.LlmSetup);
      expect(result.stepIndex).toBe(2);
    });

    it("goes LlmSetup -> Name", () => {
      const state: OnboardingState = {
        ...initialState,
        currentStep: OnboardingStep.LlmSetup,
        stepIndex: 2,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.PREV_STEP,
      });
      expect(result.currentStep).toBe(OnboardingStep.Name);
      expect(result.stepIndex).toBe(1);
    });

    it("is a no-op when already at Welcome", () => {
      const result = onboardingReducer(initialState, {
        type: OnboardingActionType.PREV_STEP,
      });
      expect(result).toBe(initialState);
    });
  });

  describe("GO_TO_STEP", () => {
    it("jumps directly to any step", () => {
      const result = onboardingReducer(initialState, {
        type: OnboardingActionType.GO_TO_STEP,
        step: OnboardingStep.LlmSetup,
      });
      expect(result.currentStep).toBe(OnboardingStep.LlmSetup);
      expect(result.stepIndex).toBe(2);
    });

    it("sets isButtonActive to true when jumping to Complete", () => {
      const state: OnboardingState = {
        ...initialState,
        isButtonActive: false,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.GO_TO_STEP,
        step: OnboardingStep.Complete,
      });
      expect(result.isButtonActive).toBe(true);
      expect(result.stepIndex).toBe(3);
    });

    it("preserves isButtonActive when jumping to non-Complete step", () => {
      const state: OnboardingState = {
        ...initialState,
        isButtonActive: false,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.GO_TO_STEP,
        step: OnboardingStep.Name,
      });
      expect(result.isButtonActive).toBe(false);
    });
  });

  describe("UPDATE_DATA", () => {
    it("merges userName into data", () => {
      const result = onboardingReducer(initialState, {
        type: OnboardingActionType.UPDATE_DATA,
        payload: { userName: "Alice" },
      });
      expect(result.data.userName).toBe("Alice");
    });

    it("merges llmProviders into data", () => {
      const result = onboardingReducer(initialState, {
        type: OnboardingActionType.UPDATE_DATA,
        payload: { llmProviders: ["openai", "anthropic"] },
      });
      expect(result.data.llmProviders).toEqual(["openai", "anthropic"]);
    });

    it("preserves existing data fields when merging new ones", () => {
      const state: OnboardingState = {
        ...initialState,
        data: { userName: "Alice" },
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.UPDATE_DATA,
        payload: { llmProviders: ["openai"] },
      });
      expect(result.data.userName).toBe("Alice");
      expect(result.data.llmProviders).toEqual(["openai"]);
    });
  });

  describe("SET_BUTTON_ACTIVE", () => {
    it("sets isButtonActive to false", () => {
      const result = onboardingReducer(initialState, {
        type: OnboardingActionType.SET_BUTTON_ACTIVE,
        isButtonActive: false,
      });
      expect(result.isButtonActive).toBe(false);
    });

    it("sets isButtonActive to true", () => {
      const state: OnboardingState = {
        ...initialState,
        isButtonActive: false,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.SET_BUTTON_ACTIVE,
        isButtonActive: true,
      });
      expect(result.isButtonActive).toBe(true);
    });
  });

  describe("SET_LOADING", () => {
    it("sets isLoading to true", () => {
      const result = onboardingReducer(initialState, {
        type: OnboardingActionType.SET_LOADING,
        isLoading: true,
      });
      expect(result.isLoading).toBe(true);
    });

    it("sets isLoading to false", () => {
      const state: OnboardingState = {
        ...initialState,
        isLoading: true,
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.SET_LOADING,
        isLoading: false,
      });
      expect(result.isLoading).toBe(false);
    });
  });

  describe("RESET", () => {
    it("returns to initial state", () => {
      const state: OnboardingState = {
        currentStep: OnboardingStep.Complete,
        stepIndex: 3,
        totalSteps: 3,
        data: { userName: "Alice", llmProviders: ["openai"] },
        isButtonActive: false,
        isLoading: true,
        error: "some error",
      };
      const result = onboardingReducer(state, {
        type: OnboardingActionType.RESET,
      });
      expect(result).toEqual(initialState);
    });
  });

  describe("unknown action", () => {
    it("returns state unchanged for unknown action type", () => {
      const result = onboardingReducer(initialState, {
        type: "UNKNOWN_ACTION" as OnboardingActionType,
      } as any);
      expect(result).toBe(initialState);
    });
  });
});
