import type { Meta, StoryObj } from "@storybook/react";
import { SWRConfig } from "swr";
import { UserProvider } from "@/providers/UserProvider";
import { BuildOnboardingProvider } from "@/app/craft/onboarding/BuildOnboardingProvider";
import ModelPickerButton from "@/app/craft/components/ModelPickerButton";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  LLMProviderDescriptor,
  LLMProviderResponse,
} from "@/lib/languageModels/types";

const SWR_NO_FETCH = {
  provider: () => new Map(),
  revalidateOnMount: false,
  revalidateIfStale: false,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
};

const llmProviders: LLMProviderDescriptor[] = [
  {
    id: 1,
    name: "Anthropic",
    provider: "anthropic",
    provider_display_name: "Anthropic",
    model_configurations: [
      {
        name: "claude-opus-4-8",
        display_name: "Claude Opus 4.8",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
        supports_reasoning: true,
        effectiveDisplayName: "Claude Opus 4.8",
      },
      {
        name: "claude-sonnet-4-6",
        display_name: "Claude Sonnet 4.6",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
        supports_reasoning: true,
        effectiveDisplayName: "Claude Sonnet 4.6",
      },
    ],
  },
];

const llmResponse: LLMProviderResponse<LLMProviderDescriptor> = {
  providers: llmProviders,
  default_text: null,
  default_vision: null,
};

const fallback = { [SWR_KEYS.llmProviders]: llmResponse };

const meta: Meta<typeof ModelPickerButton> = {
  title: "Apps/Craft/Model Picker Button",
  component: ModelPickerButton,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <SWRConfig value={{ ...SWR_NO_FETCH, fallback }}>
        <UserProvider>
          <BuildOnboardingProvider>
            <Story />
          </BuildOnboardingProvider>
        </UserProvider>
      </SWRConfig>
    ),
  ],
  args: {
    onChange: (selection) => console.log("change", selection),
  },
};

export default meta;
type Story = StoryObj<typeof ModelPickerButton>;

/** No selection — shows the recommended default for the configured provider. */
export const Default: Story = {
  args: { selection: null },
};

/** A specific model is selected and shown on the pill. */
export const Selected: Story = {
  args: {
    selection: {
      provider: "anthropic",
      providerName: "Anthropic",
      modelName: "claude-sonnet-4-6",
    },
  },
};

/** Disabled — e.g. after the session's first message locks the model. */
export const Disabled: Story = {
  args: {
    selection: {
      provider: "anthropic",
      providerName: "Anthropic",
      modelName: "claude-opus-4-8",
    },
    disabled: true,
  },
};
