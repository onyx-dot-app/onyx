import type { Route } from "next";
import { OnboardingStep } from "@/lib/onboarding/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SvgGlobe, SvgImage, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { LLMProviderName } from "@/lib/languageModels/types";

// Modules cannot call hooks, so the configs below hold message keys (inside the
// `onboarding` namespace) and the consuming components resolve them with `t`.
type StepConfig = {
  index: number;
  titleKey: string;
};

export const STEP_CONFIG = {
  [OnboardingStep.PreStep]: { index: 0, titleKey: "steps.preStep.title" },
  [OnboardingStep.Name]: { index: 1, titleKey: "steps.name.title" },
  [OnboardingStep.LlmSetup]: { index: 2, titleKey: "steps.llmSetup.title" },
  [OnboardingStep.OptionalSetup]: {
    index: 3,
    titleKey: "steps.optionalSetup.title",
  },
  [OnboardingStep.PostStep]: { index: 4, titleKey: "steps.postStep.title" },
} as const satisfies Record<OnboardingStep, StepConfig>;

/** The numbered steps, in order. The pre-step and post-step are not counted. */
export const NUMBERED_STEPS = [
  OnboardingStep.Name,
  OnboardingStep.LlmSetup,
  OnboardingStep.OptionalSetup,
] as const;

export const TOTAL_STEPS = NUMBERED_STEPS.length;

/** A numbered step's number (1 to n), or null for the pre-step and post-step. */
export function stepNumber(step: OnboardingStep): number | null {
  const index = NUMBERED_STEPS.findIndex((numbered) => numbered === step);
  return index === -1 ? null : index + 1;
}

/**
 * How full the progress circle is: step i of n is i/(n+1), so the last step
 * still shows one more Next to go. Only the post-step is full (a check).
 */
export function stepProgress(step: OnboardingStep): number {
  if (step === OnboardingStep.PostStep) return 100;
  const number = stepNumber(step);
  return number === null ? 0 : (number / (TOTAL_STEPS + 1)) * 100;
}

export const STEP_NAVIGATION: Record<
  OnboardingStep,
  { next?: OnboardingStep; prev?: OnboardingStep }
> = {
  [OnboardingStep.PreStep]: { next: OnboardingStep.Name },
  [OnboardingStep.Name]: {
    next: OnboardingStep.LlmSetup,
    prev: OnboardingStep.PreStep,
  },
  [OnboardingStep.LlmSetup]: {
    next: OnboardingStep.OptionalSetup,
    prev: OnboardingStep.Name,
  },
  [OnboardingStep.OptionalSetup]: {
    next: OnboardingStep.PostStep,
    prev: OnboardingStep.LlmSetup,
  },
  [OnboardingStep.PostStep]: { prev: OnboardingStep.OptionalSetup },
};

export type FinalSetupItemConfig = {
  titleKey: string;
  descriptionKey: string;
  icon: IconFunctionComponent;
  buttonTextKey: string;
  buttonHref: Route;
};

export const FINAL_SETUP_CONFIG = [
  {
    titleKey: "finalStep.webSearch.title",
    descriptionKey: "finalStep.webSearch.description",
    icon: SvgGlobe,
    buttonTextKey: "finalStep.webSearch.button.label",
    buttonHref: ADMIN_ROUTES.WEB_SEARCH.path,
  },
  {
    titleKey: "finalStep.imageGeneration.title",
    descriptionKey: "finalStep.imageGeneration.description",
    icon: SvgImage,
    buttonTextKey: "finalStep.imageGeneration.button.label",
    buttonHref: ADMIN_ROUTES.IMAGE_GENERATION.path,
  },
  {
    titleKey: "finalStep.inviteTeam.title",
    descriptionKey: "finalStep.inviteTeam.description",
    icon: SvgUsers,
    buttonTextKey: "finalStep.inviteTeam.button.label",
    buttonHref: ADMIN_ROUTES.USERS.path,
  },
] as const satisfies readonly FinalSetupItemConfig[];

/** The providers the LLM step offers, in order. The rest are in the admin panel. */
export const ONBOARDING_LLM_PROVIDERS: readonly LLMProviderName[] = [
  LLMProviderName.OPENAI,
  LLMProviderName.ANTHROPIC,
  LLMProviderName.VERTEX_AI,
  LLMProviderName.LITELLM_PROXY,
  LLMProviderName.OLLAMA_CHAT,
  LLMProviderName.LM_STUDIO,
];
