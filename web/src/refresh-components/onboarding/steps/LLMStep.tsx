import React, { memo } from "react";
import SvgCpu from "@/icons/cpu";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import SvgExternalLink from "@/icons/external-link";
import { Separator } from "@/components/ui/separator";
import LLMProvider from "../components/LLMProvider";
import { OnboardingActions, OnboardingState } from "../types";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { PROVIDER_ICON_MAP } from "../constants";

type LLMStepProps = {
  state: OnboardingState;
  actions: OnboardingActions;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
};

const LLMStepInner = ({
  state: onboardingState,
  actions: onboardingActions,
  llmDescriptors,
}: LLMStepProps) => {
  return (
    <div className="flex flex-col items-center justify-between w-full max-w-[800px] p-spacing-inline rounded-16 border border-border-01 bg-background-tint-00">
      <div className="flex gap-spacing-interline justify-between h-full w-full">
        <div className="flex mx-spacing-interline mt-spacing-interline gap-spacing-inline">
          <div className="h-full p-spacing-inline-mini">
            <SvgCpu className="w-4 h-4 stroke-text-03" />
          </div>
          <div>
            <Text text04 mainUiAction>
              Connect your LLM models
            </Text>
            <Text text03 secondaryBody>
              Onyx supports both popular providers and self-hosted models.
            </Text>
          </div>
        </div>
        <div className="p-spacing-inline-mini">
          <Button tertiary rightIcon={SvgExternalLink}>
            View in Admin Panel
          </Button>
        </div>
      </div>

      <div className="p-spacing-interline w-full">
        <Separator className="my-spacing-interline" />
      </div>
      <div className="flex flex-wrap gap-spacing-inline [&>*:last-child:nth-child(odd)]:basis-full">
        {llmDescriptors.map((llmDescriptor) => (
          <div className="basis-[calc(50%-var(--spacing-inline)/2)] grow">
            <LLMProvider
              title={llmDescriptor.title}
              description={llmDescriptor.display_name}
              icon={PROVIDER_ICON_MAP[llmDescriptor.name]}
            />
          </div>
        ))}

        <div className="basis-[calc(50%-var(--spacing-inline)/2)] grow">
          <LLMProvider
            title="Custom Models"
            description="Connect models from other providers or your self-hosted models."
          />
        </div>
      </div>
    </div>
  );
};

const LLMStep = memo(LLMStepInner);
export default LLMStep;
