"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { InputHorizontal, Section } from "@opal/layouts";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import type { ModelRoleName } from "@/lib/badges/components";
import {
  useAdminLanguageModels,
  useAdminLanguageModelsWithImageModels,
  useDecisionModel,
} from "@/lib/languageModels/hooks";
import type {
  DefaultModel,
  LLMProviderView,
  ModelCapability,
  ModelConfiguration,
} from "@/lib/languageModels/types";
import { useSettings } from "@/lib/settings/hooks";
import { useImageGenerationConfigs } from "@/lib/imageGeneration/hooks";
import type { ImageGenerationConfigView } from "@/lib/imageGeneration/types";

/** A deployment default: the backend's `ModelRole`. */
export type DefaultRole = ModelRoleName;

/** A default the deployment holds now. */
export interface CurrentDefault {
  role: DefaultRole;
  providerId: number;
  modelName: string;
  /** The image default's config, to clear or replace it. */
  imageProviderId?: string;
}

/** A replacement picked in a role's select: a model configuration id, or
 *  null for the role's "no model" choice (Chat Default, No Default). */
export interface DefaultChoice {
  id: number | null;
}

/** The chosen replacement per affected default. A role with a "no model"
 *  choice that is not picked keeps that choice. */
export type DefaultChoices = Partial<Record<DefaultRole, DefaultChoice>>;

const ROLE_ORDER: DefaultRole[] = [
  "chat",
  "image_generation",
  "image_processing",
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
    const byRole: Partial<Record<DefaultRole, DefaultModel | null>> = {
      chat: defaultText,
      image_processing: defaultVision,
      chat_naming: defaultChatNaming,
      search_selection: defaultSearchSelection,
      decision,
      craft: defaultCraft,
    };
    const defaults: CurrentDefault[] = [];
    for (const role of ROLE_ORDER) {
      if (role === "image_generation") {
        if (imageDefault) {
          defaults.push({
            role,
            providerId: imageDefault.llm_provider_id,
            modelName: imageDefault.model_name,
            imageProviderId: imageDefault.image_provider_id,
          });
        }
        continue;
      }
      const model = byRole[role];
      if (model) {
        defaults.push({
          role,
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

/** Whether a model can hold `role`'s default. */
function canHold(role: DefaultRole, model: ModelConfiguration): boolean {
  if (role === "image_generation")
    return model.supports_image_generation === true;
  if (!model.is_visible || model.id == null) return false;
  if (role === "decision") return model.supports_decisions === true;
  if (model.supports_chat === false) return false;
  return role !== "image_processing" || model.supports_image_input;
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
}): (role: DefaultRole) => LLMProviderView[] {
  const { llmProviders } = useAdminLanguageModelsWithImageModels();
  const { providers: decisionProviders } = useDecisionModel();

  return (role: DefaultRole) => {
    const source =
      role === "decision" ? (decisionProviders ?? []) : (llmProviders ?? []);
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
          canHold(role, model)
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
 * The backend's role changes for the chosen replacements (a
 * model, or null to clear), and the image default's new config: its
 * `image_provider_id`, null when it is lost, or undefined when untouched.
 */
export function buildDefaultChanges(
  affected: CurrentDefault[],
  candidates: (role: DefaultRole) => LLMProviderView[],
  choices: DefaultChoices,
  imageConfigs: ImageGenerationConfigView[]
): {
  defaultChanges: Record<string, DefaultModel | null>;
  imageDefault: string | null | undefined;
} {
  const defaultChanges: Record<string, DefaultModel | null> = {};
  let imageDefault: string | null | undefined;
  for (const current of affected) {
    const choice = choices[current.role];
    const id = choice?.id ?? null;
    if (current.role === "image_generation") {
      imageDefault =
        id === null
          ? null
          : (imageConfigs.find((c) => c.model_configuration_id === id)
              ?.image_provider_id ?? null);
      continue;
    }
    defaultChanges[current.role] =
      id === null ? null : choiceToDefault(candidates(current.role), id);
  }
  return { defaultChanges, imageDefault };
}

/** Whether every affected default with a possible replacement has one. */
export function choicesComplete(
  affected: CurrentDefault[],
  candidates: (role: DefaultRole) => LLMProviderView[],
  choices: DefaultChoices
): boolean {
  return affected.every(
    (d) =>
      NULLABLE_ROLES.has(d.role) ||
      candidates(d.role).length === 0 ||
      choices[d.role]?.id != null
  );
}

/**
 * A role's row copy: the exact title and description of the setting that
 * picks its model, and what happens when no model can take it over.
 */
function useRoleCopy(): Record<
  DefaultRole,
  { title: string; description?: string; lost?: string }
> {
  const t = useTranslations("admin.languageModels.defaultChanges");
  const languageModels = useTranslations("admin.languageModels");
  const chatPreferences = useTranslations("admin.chatPreferences");
  const decisionModels = useTranslations("admin.decisionModels");
  const indexSettings = useTranslations("admin.indexSettings");
  const craftPreferences = useTranslations("admin.craftPreferences");
  return {
    chat: {
      title: languageModels("defaultModel.title"),
      description: languageModels("defaultModel.description"),
      lost: t("flows.chat.lost"),
    },
    image_generation: {
      title: languageModels("imageGeneration.defaultModel.title"),
      description: languageModels("imageGeneration.defaultModel.description"),
    },
    image_processing: {
      title: indexSettings("captioningModel.title"),
      description: indexSettings("captioningModel.description"),
    },
    chat_naming: {
      title: chatPreferences("chatNaming.title"),
      description: chatPreferences("chatNaming.description"),
    },
    search_selection: {
      title: chatPreferences("searchDecisionModel.title"),
      description: chatPreferences("searchDecisionModel.description"),
    },
    decision: {
      title: decisionModels("decisionModel.title"),
      description: decisionModels("decisionModel.description"),
      lost: t("flows.decision.lost"),
    },
    craft: {
      title: craftPreferences("defaultModel.label"),
      lost: t("cleared"),
    },
  };
}

/** Roles whose setting offers a "no model" choice (Chat Default, No Default),
 *  so their select always shows. */
const NULLABLE_ROLES: ReadonlySet<DefaultRole> = new Set([
  "chat_naming",
  "search_selection",
  "image_generation",
  "image_processing",
]);

const CHAT: readonly ModelCapability[] = ["chat"];
const VISION: readonly ModelCapability[] = ["vision"];
const DECISION: readonly ModelCapability[] = ["decision"];
const IMAGE: readonly ModelCapability[] = ["image"];

interface RoleSelectProps {
  role: DefaultRole;
  providers: LLMProviderView[];
  choice: DefaultChoice | undefined;
  onChange: (choice: DefaultChoice) => void;
}

/** A role's select, with the same props as the setting that picks it. */
function RoleSelect({ role, providers, choice, onChange }: RoleSelectProps) {
  const chatPreferences = useTranslations("admin.chatPreferences");
  const imageGeneration = useTranslations(
    "admin.languageModels.imageGeneration"
  );
  const settings = useSettings();
  const grouped = !settings.hide_provider_grouping;
  const value = choice?.id ?? null;
  const pick = (id: number | null) => onChange({ id });

  switch (role) {
    case "chat_naming":
    case "search_selection":
      return (
        <SimpleModelSelector
          nullable
          capabilities={CHAT}
          // Unset, a task runs on the chat's own model.
          globalDefault={{
            label: chatPreferences("taskModels.chatDefault.label"),
          }}
          providers={providers}
          value={value}
          grouped={grouped}
          onChange={pick}
        />
      );
    case "image_generation":
      return (
        <SimpleModelSelector
          nullable
          capabilities={IMAGE}
          globalDefault={{
            label: imageGeneration("defaultModel.noDefault.label"),
            description: imageGeneration("defaultModel.noDefault.description"),
          }}
          providers={providers}
          value={value}
          onChange={pick}
        />
      );
    case "image_processing":
      return (
        <SimpleModelSelector
          nullable
          capabilities={VISION}
          providers={providers}
          value={value}
          grouped={grouped}
          onChange={pick}
        />
      );
    case "decision":
      return (
        <SimpleModelSelector
          capabilities={DECISION}
          providers={providers}
          value={value}
          grouped={grouped}
          onChange={pick}
        />
      );
    case "chat":
    case "craft":
      return (
        <SimpleModelSelector
          capabilities={CHAT}
          providers={providers}
          value={value}
          grouped={grouped}
          onChange={pick}
        />
      );
  }
}

interface DefaultChoiceRowsProps {
  affected: CurrentDefault[];
  candidates: (role: DefaultRole) => LLMProviderView[];
  choices: DefaultChoices;
  onChange: (role: DefaultRole, choice: DefaultChoice) => void;
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
  const copy = useRoleCopy();
  return (
    <Section alignItems="stretch" gap={4} height="fit">
      {affected.map((current) => {
        const options = candidates(current.role);
        return (
          <InputHorizontal
            key={current.role}
            title={copy[current.role].title}
            description={copy[current.role].description}
            center
            withLabel
            fillInput
          >
            {/* A role with a "no model" choice always has a select. */}
            {NULLABLE_ROLES.has(current.role) || options.length > 0 ? (
              <RoleSelect
                role={current.role}
                providers={options}
                choice={choices[current.role]}
                onChange={(choice) => onChange(current.role, choice)}
              />
            ) : (
              <Text as="p" font="secondary-body" color="status-warning-05">
                {copy[current.role].lost}
              </Text>
            )}
          </InputHorizontal>
        );
      })}
    </Section>
  );
}
