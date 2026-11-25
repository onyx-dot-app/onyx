"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { InputHorizontal, Section } from "@opal/layouts";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import {
  useAdminLanguageModels,
  useAdminLanguageModelsWithImageModels,
  useDecisionModel,
} from "@/lib/languageModels/hooks";
import type {
  DefaultModel,
  LLMProviderView,
  ModelConfiguration,
  ModelKind,
} from "@/lib/languageModels/types";
import { useImageGenerationConfigs } from "@/lib/imageGeneration/hooks";
import type { ImageGenerationConfigView } from "@/lib/imageGeneration/types";

/** A deployment default: the backend's flow name, or the image default. */
export type DefaultFlow =
  | "chat"
  | "vision"
  | "chat_naming"
  | "search_selection"
  | "decision"
  | "craft"
  | "image";

/** A default the deployment holds now. */
export interface CurrentDefault {
  flow: DefaultFlow;
  providerId: number;
  modelName: string;
  /** The image default's config, to clear or replace it. */
  imageProviderId?: string;
}

/** The chosen replacement per affected default: a model configuration id,
 *  or null when no model can take it over and it is cleared. */
export type DefaultChoices = Partial<Record<DefaultFlow, number | null>>;

const FLOW_ORDER: DefaultFlow[] = [
  "chat",
  "image",
  "vision",
  "chat_naming",
  "search_selection",
  "decision",
  "craft",
];

/** Every default the deployment holds, chat first. */
export function useCurrentDefaults(): CurrentDefault[] {
  const {
    defaultText,
    defaultVision,
    defaultChatNaming,
    defaultSearchSelection,
    defaultCraft,
  } = useAdminLanguageModels();
  const { model: decision } = useDecisionModel();
  const { defaultConfig: imageDefault } = useImageGenerationConfigs();

  return useMemo(() => {
    const byFlow: Partial<Record<DefaultFlow, DefaultModel | null>> = {
      chat: defaultText,
      vision: defaultVision,
      chat_naming: defaultChatNaming,
      search_selection: defaultSearchSelection,
      decision,
      craft: defaultCraft,
    };
    const defaults: CurrentDefault[] = [];
    for (const flow of FLOW_ORDER) {
      if (flow === "image") {
        if (imageDefault) {
          defaults.push({
            flow,
            providerId: imageDefault.llm_provider_id,
            modelName: imageDefault.model_name,
            imageProviderId: imageDefault.image_provider_id,
          });
        }
        continue;
      }
      const model = byFlow[flow];
      if (model) {
        defaults.push({
          flow,
          providerId: model.provider_id,
          modelName: model.model_name,
        });
      }
    }
    return defaults;
  }, [
    defaultText,
    defaultVision,
    defaultChatNaming,
    defaultSearchSelection,
    defaultCraft,
    decision,
    imageDefault,
  ]);
}

/** Whether a model can hold `flow`'s default. */
function canHold(flow: DefaultFlow, model: ModelConfiguration): boolean {
  if (flow === "image") return model.supports_image_generation === true;
  if (!model.is_visible || model.id == null) return false;
  if (flow === "decision") return model.supports_decisions === true;
  if (model.supports_chat === false) return false;
  return flow !== "vision" || model.supports_image_input;
}

/**
 * The providers whose models can take over each affected default.
 * `exclude` drops a provider being deleted; `override` replaces a provider
 * with its form state, for a save that changes its models.
 */
export function useDefaultCandidates({
  exclude,
  override,
  disconnecting,
}: {
  exclude?: number;
  override?: LLMProviderView;
  /** Image models of `override` that the save disconnects. */
  disconnecting?: ReadonlySet<string>;
}): (flow: DefaultFlow) => LLMProviderView[] {
  const { llmProviders } = useAdminLanguageModelsWithImageModels();
  const { providers: decisionProviders } = useDecisionModel();

  return (flow: DefaultFlow) => {
    const source =
      flow === "decision" ? (decisionProviders ?? []) : (llmProviders ?? []);
    return source
      .filter((provider) => provider.id !== exclude)
      .map((provider) =>
        override && provider.id === override.id
          ? {
              ...override,
              // The form leaves image models out; keep the connected ones.
              model_configurations: [
                ...override.model_configurations,
                ...provider.model_configurations.filter(
                  (m) =>
                    m.supports_image_generation === true &&
                    !disconnecting?.has(m.name)
                ),
              ],
            }
          : provider
      )
      .map((provider) => ({
        ...provider,
        model_configurations: provider.model_configurations.filter((model) =>
          canHold(flow, model)
        ),
      }))
      .filter((provider) => provider.model_configurations.length > 0);
  };
}

/** The model a choice names, as the backend's default. */
export function choiceToDefault(
  candidates: LLMProviderView[],
  modelConfigurationId: number
): DefaultModel | null {
  for (const provider of candidates) {
    const model = provider.model_configurations.find(
      (m) => m.id === modelConfigurationId
    );
    if (model) return { provider_id: provider.id, model_name: model.name };
  }
  return null;
}

/**
 * The backend's default changes for the chosen replacements, by flow (a
 * model, or null to clear), and the image default's new config: its
 * `image_provider_id`, null when it is lost, or undefined when untouched.
 */
export function buildDefaultChanges(
  affected: CurrentDefault[],
  candidates: (flow: DefaultFlow) => LLMProviderView[],
  choices: DefaultChoices,
  imageConfigs: ImageGenerationConfigView[]
): {
  defaultChanges: Record<string, DefaultModel | null>;
  imageDefault: string | null | undefined;
} {
  const defaultChanges: Record<string, DefaultModel | null> = {};
  let imageDefault: string | null | undefined;
  for (const current of affected) {
    const choice = choices[current.flow] ?? null;
    if (current.flow === "image") {
      imageDefault =
        choice === null
          ? null
          : (imageConfigs.find((c) => c.model_configuration_id === choice)
              ?.image_provider_id ?? null);
      continue;
    }
    defaultChanges[current.flow] =
      choice === null
        ? null
        : choiceToDefault(candidates(current.flow), choice);
  }
  return { defaultChanges, imageDefault };
}

/** Whether every affected default with a possible replacement has one. */
export function choicesComplete(
  affected: CurrentDefault[],
  candidates: (flow: DefaultFlow) => LLMProviderView[],
  choices: DefaultChoices
): boolean {
  return affected.every(
    (d) => candidates(d.flow).length === 0 || choices[d.flow] != null
  );
}

/** A default's row title and what happens when no model can take it over. */
function useFlowCopy(): Record<DefaultFlow, { title: string; lost: string }> {
  const t = useTranslations("admin.languageModels.defaultChanges");
  return {
    chat: { title: t("flows.chat.title"), lost: t("flows.chat.lost") },
    image: { title: t("flows.image.title"), lost: t("flows.image.lost") },
    vision: { title: t("flows.vision.title"), lost: t("cleared") },
    chat_naming: { title: t("flows.chatNaming.title"), lost: t("cleared") },
    search_selection: {
      title: t("flows.searchSelection.title"),
      lost: t("cleared"),
    },
    decision: {
      title: t("flows.decision.title"),
      lost: t("flows.decision.lost"),
    },
    craft: { title: t("flows.craft.title"), lost: t("cleared") },
  };
}

const IMAGE_KINDS: readonly ModelKind[] = ["image"];
const CHAT_KINDS: readonly ModelKind[] = ["chat"];

interface DefaultChoiceRowsProps {
  affected: CurrentDefault[];
  candidates: (flow: DefaultFlow) => LLMProviderView[];
  choices: DefaultChoices;
  onChange: (flow: DefaultFlow, modelConfigurationId: number) => void;
}

/**
 * One row per affected default: a picker for its new model, or, when no
 * other model can take it over, what turns off.
 */
export function DefaultChoiceRows({
  affected,
  candidates,
  choices,
  onChange,
}: DefaultChoiceRowsProps) {
  const t = useTranslations("admin.languageModels.defaultChanges");
  const copy = useFlowCopy();
  return (
    <Section alignItems="stretch" gap={1} height="fit">
      {affected.map((current) => {
        const options = candidates(current.flow);
        return (
          <InputHorizontal
            key={current.flow}
            title={copy[current.flow].title}
            description={t("current", { model: current.modelName })}
            center
          >
            {options.length > 0 ? (
              <SimpleModelSelector
                providers={options}
                value={choices[current.flow] ?? null}
                onChange={(id) => onChange(current.flow, id)}
                modelKinds={current.flow === "image" ? IMAGE_KINDS : CHAT_KINDS}
                includeDecisionOnly={current.flow === "decision"}
                placeholder={t("placeholder")}
              />
            ) : (
              <Text as="p" font="secondary-body" color="status-warning-05">
                {copy[current.flow].lost}
              </Text>
            )}
          </InputHorizontal>
        );
      })}
    </Section>
  );
}
