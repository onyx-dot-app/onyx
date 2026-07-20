/**
 * Regression test for the "everything renders disabled" onboarding bug.
 *
 * LLMStep used to wrap its whole section in `<Disabled>` while ALSO passing
 * `disabled` straight through to each `LLMProviderCard`, which wraps itself
 * in its own `<Disabled>`. The two wrappers compounded, so the cards ended
 * up visibly darker/more disabled-looking than every other control on the
 * step (e.g. the "View in Admin Panel" button), even though only one
 * `disabled` value was ever in play.
 */
import { render, screen } from "@tests/setup/test-utils";
import LLMStep from "@/sections/onboarding/steps/LLMStep";
import { OnboardingStep } from "@/interfaces/onboarding";
import type { OnboardingActions, OnboardingState } from "@/interfaces/onboarding";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { WellKnownLLMProviderDescriptor } from "@/lib/languageModels/types";

const WELL_KNOWN_PROVIDERS: WellKnownLLMProviderDescriptor[] = [
  { name: "openai", known_models: [], recommended_default_model: null },
  { name: "anthropic", known_models: [], recommended_default_model: null },
];

const noop = () => {};
const actions: OnboardingActions = {
  nextStep: noop,
  prevStep: noop,
  goToStep: noop,
  setButtonActive: noop,
  updateName: noop,
  updateData: noop,
  setLoading: noop,
  setError: noop,
  reset: noop,
};

function makeState(currentStep: OnboardingStep): OnboardingState {
  return {
    currentStep,
    stepIndex: 1,
    totalSteps: 3,
    data: {},
    isButtonActive: true,
  };
}

function renderLLMStep(props: { currentStep: OnboardingStep; disabled?: boolean }) {
  return render(
    <LLMStep
      state={makeState(props.currentStep)}
      actions={actions}
      disabled={props.disabled}
    />,
    {
      swrConfig: {
        fallback: { [SWR_KEYS.wellKnownLlmProviders]: WELL_KNOWN_PROVIDERS },
      },
    }
  );
}

describe("LLMStep", () => {
  test("provider cards and admin link are not disabled on the active LLM setup step", () => {
    renderLLMStep({ currentStep: OnboardingStep.LlmSetup, disabled: false });

    const adminLink = screen.getByRole("link", { name: /view in admin panel/i });
    expect(adminLink).not.toHaveAttribute("aria-disabled", "true");

    const openaiCard = screen.getByText("GPT").closest('[role="button"]');
    expect(openaiCard).not.toBeNull();
    expect(openaiCard).not.toHaveAttribute("aria-disabled", "true");
    expect(openaiCard?.closest("[data-opal-disabled]")).toBeNull();
  });

  test("disabled preview step never nests two data-opal-disabled wrappers around a card", () => {
    renderLLMStep({ currentStep: OnboardingStep.Name, disabled: true });

    const openaiCard = screen.getByText("GPT").closest('[role="button"]')!;
    expect(openaiCard.closest("[aria-disabled]")).toHaveAttribute(
      "aria-disabled",
      "true"
    );

    // Count every ancestor (including the card's own wrapper) that carries
    // the disabled marker. Exactly one is expected — a second means the
    // opacity/pointer-events are compounding again.
    let disabledAncestors = 0;
    for (
      let el: Element | null = openaiCard;
      el;
      el = el.parentElement
    ) {
      if (el.hasAttribute("data-opal-disabled")) disabledAncestors++;
    }
    expect(disabledAncestors).toBe(1);
  });

  test("LLMStep's own container is not wrapped in a blanket Disabled div", () => {
    renderLLMStep({ currentStep: OnboardingStep.Name, disabled: true });

    const step = screen.getByLabelText("onboarding-llm-step");
    expect(step).not.toHaveAttribute("data-opal-disabled");
  });
});
