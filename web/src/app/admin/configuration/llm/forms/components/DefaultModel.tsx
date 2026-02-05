"use client";

import { Card } from "@/refresh-components/cards";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { DefaultModelSelectorProps } from "../../interfaces";
import { Section } from "@/layouts/general-layouts";
import { useMemo } from "react";
import { LLM_ADMIN_URL } from "../../constants";
import * as InputLayouts from "@/layouts/input-layouts";

export function DefaultModelSelector({
  existingLlmProviders,
  defaultLlmModel,
}: DefaultModelSelectorProps) {
  // Flatten all models from all providers into a single list
  const models = useMemo(() => {
    return existingLlmProviders.flatMap((provider) =>
      provider.model_configurations
        .filter((model) => model.is_visible)
        .map((model) => ({
          model_display_name: model.display_name || model.name,
          model_name: model.name,
          provider_display_name: provider.name || provider.provider,
          provider_id: provider.id,
        }))
    );
  }, [existingLlmProviders]);

  const onModelChange = (provider_id: number, model_name: string) => {
    fetch(`${LLM_ADMIN_URL}/default`, {
      method: "POST",
      body: JSON.stringify({
        provider_id,
        model_name,
      }),
    });
  };

  // Create a composite value string for the select (provider_id:model_name)
  // Fall back to the first model if no default is set
  const currentValue = useMemo(() => {
    if (defaultLlmModel) {
      return `${defaultLlmModel.provider_id}:${defaultLlmModel.model_name}`;
    }
    const firstModel = models[0];
    if (firstModel) {
      return `${firstModel.provider_id}:${firstModel.model_name}`;
    }
    return undefined;
  }, [defaultLlmModel, models]);

  const handleValueChange = (value: string) => {
    const separatorIndex = value.indexOf(":");
    const providerId = parseInt(value.slice(0, separatorIndex), 10);
    const modelName = value.slice(separatorIndex + 1);

    onModelChange(providerId, modelName);
  };

  return (
    <Card>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        height="fit"
      >
        <InputLayouts.Horizontal
          title="Default Model"
          description="This model will be used by Onyx by default in your chats."
        >
          <InputSelect value={currentValue} onValueChange={handleValueChange}>
            <InputSelect.Trigger placeholder="Select a model..." />
            <InputSelect.Content>
              {models.map((model) => (
                <InputSelect.Item
                  key={`${model.provider_id}:${model.model_name}`}
                  value={`${model.provider_id}:${model.model_name}`}
                  description={model.provider_display_name}
                >
                  {model.model_display_name}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>
        </InputLayouts.Horizontal>
      </Section>
    </Card>
  );
}
