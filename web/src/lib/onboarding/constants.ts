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
  iconPercentage: number;
};

export const STEP_CONFIG = {
  [OnboardingStep.Welcome]: {
    index: 0,
    titleKey: "steps.welcome.title",
    iconPercentage: 10,
  },
  [OnboardingStep.Name]: {
    index: 1,
    titleKey: "steps.name.title",
    iconPercentage: 40,
  },
  [OnboardingStep.LlmSetup]: {
    index: 2,
    titleKey: "steps.llmSetup.title",
    iconPercentage: 70,
  },
  [OnboardingStep.Complete]: {
    index: 3,
    titleKey: "steps.complete.title",
    iconPercentage: 100,
  },
} as const satisfies Record<OnboardingStep, StepConfig>;

export const TOTAL_STEPS = 3;

export const STEP_NAVIGATION: Record<
  OnboardingStep,
  { next?: OnboardingStep; prev?: OnboardingStep }
> = {
  [OnboardingStep.Welcome]: { next: OnboardingStep.Name },
  [OnboardingStep.Name]: {
    next: OnboardingStep.LlmSetup,
    prev: OnboardingStep.Welcome,
  },
  [OnboardingStep.LlmSetup]: {
    next: OnboardingStep.Complete,
    prev: OnboardingStep.Name,
  },
  [OnboardingStep.Complete]: { prev: OnboardingStep.LlmSetup },
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
