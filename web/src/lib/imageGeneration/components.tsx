"use client";

import { useTranslations } from "next-intl";
import { InputSingleSelect, type SelectDivider } from "@opal/components";
import { InputHorizontal, toast } from "@opal/layouts";
import { SvgSlash } from "@opal/icons";
import { getModelIcon } from "@/lib/languageModels/utils";
import {
  useImageGenerationConfigs,
  useImageGenerationProviders,
} from "@/lib/imageGeneration/hooks";
import {
  setDefaultImageGenerationConfig,
  unsetDefaultImageGenerationConfig,
} from "@/lib/imageGeneration/svc";
import type {
  ImageGenerationConfigView,
  ImageGenerationLLMProvider,
  ImageGenerationProviderModel,
} from "@/lib/imageGeneration/types";

const NO_DEFAULT_VALUE = "__none__";

function modelTitle(model: ImageGenerationProviderModel): string {
  return model.display_name || model.name;
}

/** A connected model's title, from its provider's listing when it has one. */
function configTitle(
  config: ImageGenerationConfigView,
  providers: ImageGenerationLLMProvider[] | undefined
): string {
  const model = providers
    ?.find((provider) => provider.llm_provider_id === config.llm_provider_id)
    ?.models.find((m) => m.image_provider_id === config.image_provider_id);
  return model ? modelTitle(model) : config.model_name;
}

/**
 * The Default Image Generation Model row: the connected image models, by
 * provider, and "No Default", which turns image generation off.
 */
export function DefaultImageModelSetting() {
  const t = useTranslations("admin.languageModels.imageGeneration");
  const { configs, defaultConfig, refetch } = useImageGenerationConfigs();
  const { providers } = useImageGenerationProviders();

  const groups = new Map<string, ImageGenerationConfigView[]>();
  for (const config of configs ?? []) {
    const name = config.llm_provider_name ?? config.llm_provider_type;
    groups.set(name, [...(groups.get(name) ?? []), config]);
  }
  const options: SelectDivider[] = Array.from(groups.entries()).map(
    ([title, groupConfigs]) => ({
      title,
      options: groupConfigs.map((config) => ({
        value: config.image_provider_id,
        title: configTitle(config, providers),
        icon: getModelIcon(config.llm_provider_type, config.model_name),
      })),
    })
  );

  async function handleChange(value: string) {
    try {
      if (value !== NO_DEFAULT_VALUE) {
        await setDefaultImageGenerationConfig(value);
      } else if (defaultConfig) {
        await unsetDefaultImageGenerationConfig(
          defaultConfig.image_provider_id
        );
      }
      await refetch();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("defaultModel.error")
      );
    }
  }

  const hasModels = (configs?.length ?? 0) > 0;
  return (
    <InputHorizontal
      title={t("defaultModel.title")}
      description={
        hasModels
          ? t("defaultModel.description")
          : t("defaultModel.emptyDescription")
      }
      center
      withLabel
    >
      <InputSingleSelect
        value={defaultConfig?.image_provider_id ?? NO_DEFAULT_VALUE}
        onValueChange={(value) => void handleChange(value)}
        placeholder={t("defaultModel.placeholder")}
        disabled={!hasModels}
        options={[
          ...options,
          {
            value: NO_DEFAULT_VALUE,
            title: t("defaultModel.noDefault.label"),
            description: t("defaultModel.noDefault.description"),
            icon: SvgSlash,
          },
        ]}
      />
    </InputHorizontal>
  );
}
