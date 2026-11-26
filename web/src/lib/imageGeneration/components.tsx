"use client";

import { useTranslations } from "next-intl";
import { InputHorizontal, toast } from "@opal/layouts";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import type { ModelCapability } from "@/lib/languageModels/types";
import { useAdminLanguageModelsWithImageModels } from "@/lib/languageModels/hooks";
import { useImageGenerationConfigs } from "@/lib/imageGeneration/hooks";
import {
  setDefaultImageGenerationConfig,
  unsetDefaultImageGenerationConfig,
} from "@/lib/imageGeneration/svc";

const IMAGE_CAPABILITIES: readonly ModelCapability[] = ["image"];
/**
 * The Image Model row: the connected image models, by
 * provider, and "No Default", which turns image generation off.
 */
export function DefaultImageModelSetting() {
  const t = useTranslations("admin.languageModels.imageGeneration");
  const { configs, defaultConfig, refetch } = useImageGenerationConfigs();
  const { llmProviders, error } = useAdminLanguageModelsWithImageModels();

  async function handleChange(modelConfigurationId: number | null) {
    try {
      if (modelConfigurationId === null) {
        if (defaultConfig) {
          await unsetDefaultImageGenerationConfig(
            defaultConfig.image_provider_id
          );
        }
      } else {
        const config = configs?.find(
          (c) => c.model_configuration_id === modelConfigurationId
        );
        if (config) {
          await setDefaultImageGenerationConfig(config.image_provider_id);
        }
      }
      await refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("defaultModel.error"));
    }
  }

  const hasModels = (configs?.length ?? 0) > 0;
  return (
    <InputHorizontal
      title={t("defaultModel.title")}
      description={t("defaultModel.description")}
      center
      withLabel
    >
      <SimpleModelSelector
        nullable
        capabilities={IMAGE_CAPABILITIES}
        providers={llmProviders ?? []}
        value={defaultConfig?.model_configuration_id ?? null}
        onChange={(modelConfigurationId) => handleChange(modelConfigurationId)}
        globalDefault={{
          label: t("defaultModel.noDefault.label"),
          description: t("defaultModel.noDefault.description"),
        }}
        placeholder={t("defaultModel.placeholder")}
        disabled={!hasModels}
        isError={error ? true : undefined}
      />
    </InputHorizontal>
  );
}
