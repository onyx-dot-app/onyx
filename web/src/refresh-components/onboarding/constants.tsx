import { OnboardingStep } from "./types";
import { FinalStepItemProps } from "./types";
import { DOCS_BASE_URL } from "@/lib/constants";
import { SvgGlobe, SvgImage, SvgUsers } from "@opal/icons";

type StepConfig = {
  index: number;
  title: string;
  buttonText: string;
  iconPercentage: number;
};

export const STEP_CONFIG: Record<OnboardingStep, StepConfig> = {
  [OnboardingStep.Welcome]: {
    index: 0,
    title: "Let's take a moment to get you set up.",
    buttonText: "Let's Go",
    iconPercentage: 10,
  },
  [OnboardingStep.Name]: {
    index: 1,
    title: "Let's take a moment to get you set up.",
    buttonText: "Next",
    iconPercentage: 40,
  },
  [OnboardingStep.LlmSetup]: {
    index: 2,
    title: "Almost there! Connect your models to start chatting.",
    buttonText: "Next",
    iconPercentage: 70,
  },
  [OnboardingStep.Complete]: {
    index: 3,
    title: "You're all set, review the optional settings or click Finish Setup",
    buttonText: "Finish Setup",
    iconPercentage: 100,
  },
} as const;

export const TOTAL_STEPS = 3;

export const HAS_FINISHED_ONBOARDING_KEY = "hasFinishedOnboarding";

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

export const FINAL_SETUP_CONFIG: FinalStepItemProps[] = [
  {
    title: "Select web search provider",
    description: "Enable Onyx to search the internet for information.",
    icon: SvgGlobe,
    buttonText: "Web Search",
    buttonHref: "/admin/configuration/web-search",
  },
  {
    title: "Enable image generation",
    description: "Set up models to create images in your chats.",
    icon: SvgImage,
    buttonText: "Image Generation",
    buttonHref: `${DOCS_BASE_URL}/overview/core_features/image_generation`,
  },
  {
    title: "Invite your team",
    description: "Manage users and permissions for your team",
    icon: SvgUsers,
    buttonText: "Manage Users",
    buttonHref: "/admin/users",
  },
];
