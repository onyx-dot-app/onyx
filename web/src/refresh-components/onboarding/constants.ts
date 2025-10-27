import { OnboardingStep } from "./types";
import SvgSearchMenu from "@/icons/search-menu";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import SvgUsers from "@/icons/users";
import SvgStep1 from "@/icons/step1";
import { FinalStepItemProps } from "./types";
import { SvgProps } from "@/icons";

type StepConfig = {
  index: number;
  title: string;
  buttonText: string;
  icon: React.FunctionComponent<SvgProps>;
};

export const STEP_CONFIG: Record<OnboardingStep, StepConfig> = {
  [OnboardingStep.Name]: {
    index: 1,
    title: "Let's take a moment to get you set up.",
    buttonText: "Next",
    icon: SvgStep1,
  },
  [OnboardingStep.LlmSetup]: {
    index: 2,
    title: "Almost there! Connect your models to start chatting.",
    buttonText: "Finish Setup",
    icon: SvgStep1,
  },
  [OnboardingStep.Complete]: {
    index: 3,
    title:
      "You're all set! It might be helpful to review the following settings.",
    buttonText: "",
    icon: SvgStep1,
  },
} as const;

export const TOTAL_STEPS = 3;

export const STEP_NAVIGATION: Record<
  OnboardingStep,
  { next?: OnboardingStep; prev?: OnboardingStep }
> = {
  [OnboardingStep.Name]: { next: OnboardingStep.LlmSetup },
  [OnboardingStep.LlmSetup]: {
    next: OnboardingStep.Complete,
    prev: OnboardingStep.Name,
  },
  [OnboardingStep.Complete]: { prev: OnboardingStep.LlmSetup },
};

export const FINAL_SETUP_CONFIG: FinalStepItemProps[] = [
  {
    title: "Set up document search with RAG (Retrieval Augmented Generation)",
    description:
      "Select embedding models used to search across large bodies of documents.",
    icon: SvgSearchMenu,
    buttonText: "Search Settings",
  },
  {
    title: "Select web search provider",
    description: "Set up web search and search across the internet.",
    icon: SvgGlobe,
    buttonText: "Web Search",
  },
  {
    title: "Enable image generation",
    description:
      "Set up image generation models to create images in your chat.",
    icon: SvgImage,
    buttonText: "Image Generation",
  },
  {
    title: "Invite your team",
    description: "Add and manage users and groups in your team.",
    icon: SvgUsers,
    buttonText: "Manage Users",
  },
];
