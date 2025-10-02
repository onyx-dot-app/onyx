import { LlmDescriptor } from "@/lib/hooks";
import { parseLlmDescriptor } from "@/lib/llm/utils";
import LLMPopover from "./input/LLMPopover";

export interface RegenerateOptionProps {
  regenerate: (modelOverRide: LlmDescriptor) => Promise<void>;
  overriddenModel?: string;
}

export default function RegenerateOption({
  regenerate,
  overriddenModel,
}: RegenerateOptionProps) {
  return (
    <LLMPopover
      requiresImageGeneration={false}
      currentModelName={overriddenModel}
      onSelect={(value) => {
        const { name, provider, modelName } = parseLlmDescriptor(
          value as string
        );
        regenerate({
          name: name,
          provider: provider,
          modelName: modelName,
        });
      }}
      compact
    />
  );
}
