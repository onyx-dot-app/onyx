"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import type { ModelConfiguration } from "@/lib/languageModels/types";
import * as Yup from "yup";
import { useInitialValues } from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  APIBaseField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { useCustomProviderNames } from "@/lib/languageModels/hooks";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import KeyValueInput, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { InputTypeIn } from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import { Button, Card, EmptyMessageCard } from "@opal/components";
import { SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import { markdown } from "@opal/utils";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import {
  Content,
  InputDivider,
  InputPadder,
  InputVertical,
} from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";

// ─── Model Configuration List ─────────────────────────────────────────────────

const MODEL_GRID_COLS = "grid-cols-[2fr_2fr_minmax(10rem,1fr)_1fr_2.25rem]";

type CustomModelConfiguration = Pick<
  ModelConfiguration,
  "name" | "max_input_tokens" | "supports_image_input"
> & {
  display_name: string;
};

interface ModelConfigurationItemProps {
  model: CustomModelConfiguration;
  onChange: (next: CustomModelConfiguration) => void;
  onRemove: () => void;
  canRemove: boolean;
}

function ModelConfigurationItem({
  model,
  onChange,
  onRemove,
  canRemove,
}: ModelConfigurationItemProps) {
  const { t } = useTranslation();
  return (
    <>
      <InputTypeIn
        placeholder={t("admin.custom_llm.model_name_placeholder")}
        value={model.name}
        onChange={(e) => onChange({ ...model, name: e.target.value })}
      />
      <InputTypeIn
        placeholder={t("admin.custom_llm.display_name_placeholder")}
        value={model.display_name}
        onChange={(e) => onChange({ ...model, display_name: e.target.value })}
      />
      <InputSelect
        value={model.supports_image_input ? "text-image" : "text-only"}
        onValueChange={(value) =>
          onChange({ ...model, supports_image_input: value === "text-image" })
        }
      >
        <InputSelect.Trigger
          placeholder={t("admin.custom_llm.input_type_placeholder")}
        />
        <InputSelect.Content>
          <InputSelect.Item value="text-only">
            {t("admin.custom_llm.text_only")}
          </InputSelect.Item>
          <InputSelect.Item value="text-image">
            {t("admin.custom_llm.text_image")}
          </InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
      <InputTypeIn
        placeholder={t("admin.custom_llm.max_tokens_default_placeholder")}
        value={model.max_input_tokens?.toString() ?? ""}
        onChange={(e) =>
          onChange({
            ...model,
            max_input_tokens:
              e.target.value === "" ? null : Number(e.target.value),
          })
        }
        type="number"
      />
      <Button
        disabled={!canRemove}
        prominence="tertiary"
        icon={SvgMinusCircle}
        onClick={onRemove}
      />
    </>
  );
}

function ModelConfigurationList() {
  const { t } = useTranslation();
  const formikProps = useFormikContext<{
    model_configurations: CustomModelConfiguration[];
  }>();
  const models = formikProps.values.model_configurations;

  function handleChange(index: number, next: CustomModelConfiguration) {
    const updated = [...models];
    updated[index] = next;
    formikProps.setFieldValue("model_configurations", updated);
  }

  function handleRemove(index: number) {
    formikProps.setFieldValue(
      "model_configurations",
      models.filter((_, i) => i !== index)
    );
  }

  function handleAdd() {
    formikProps.setFieldValue("model_configurations", [
      ...models,
      {
        name: "",
        display_name: "",
        max_input_tokens: null,
        supports_image_input: false,
      },
    ]);
  }

  return (
    <div className="w-full flex flex-col gap-y-2">
      {models.length > 0 ? (
        <div className={`grid items-center gap-1 ${MODEL_GRID_COLS}`}>
          <div className="pb-1">
            <Text mainUiAction>{t("admin.custom_llm.col_model_name")}</Text>
          </div>
          <Text mainUiAction>{t("admin.custom_llm.col_display_name")}</Text>
          <Text mainUiAction>{t("admin.custom_llm.col_input_type")}</Text>
          <Text mainUiAction>{t("admin.custom_llm.col_max_tokens")}</Text>
          <div aria-hidden />

          {models.map((model, index) => (
            <ModelConfigurationItem
              key={index}
              model={model}
              onChange={(next) => handleChange(index, next)}
              onRemove={() => handleRemove(index)}
              canRemove={models.length > 1}
            />
          ))}
        </div>
      ) : (
        <EmptyMessageCard
          title={t("admin.custom_llm.no_models")}
          padding="sm"
        />
      )}

      <Button
        prominence="secondary"
        icon={SvgPlusCircle}
        onClick={handleAdd}
        type="button"
      >
        {t("admin.custom_llm.add_model")}
      </Button>
    </div>
  );
}

function CustomConfigKeyValue() {
  const { t } = useTranslation();
  const formikProps = useFormikContext<{ custom_config_list: KeyValue[] }>();
  return (
    <KeyValueInput
      items={formikProps.values.custom_config_list}
      keyPlaceholder={t("admin.custom_llm.env_key_placeholder")}
      onChange={(items) =>
        formikProps.setFieldValue("custom_config_list", items)
      }
      addButtonLabel={t("admin.custom_llm.add_line")}
    />
  );
}

// ─── Provider Name Select ─────────────────────────────────────────────────────

function ProviderNameSelect({ disabled }: { disabled?: boolean }) {
  const { t } = useTranslation();
  const { customProviderNames } = useCustomProviderNames();
  const { values, setFieldValue } = useFormikContext<{ provider: string }>();

  const options = useMemo(
    () =>
      (customProviderNames ?? []).map((opt) => ({
        value: opt.value,
        label: opt.value,
        description: opt.label,
      })),
    [customProviderNames]
  );

  return (
    <InputComboBox
      value={values.provider}
      onValueChange={(value) => setFieldValue("provider", value)}
      options={options}
      placeholder={t("admin.custom_llm.provider_id_placeholder")}
      disabled={disabled}
      createPrefix="Use"
      dropdownMaxHeight="60vh"
    />
  );
}

// ─── Custom Config Processing ─────────────────────────────────────────────────

function keyValueListToDict(items: KeyValue[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const { key, value } of items) {
    if (key.trim() !== "") {
      result[key] = value;
    }
  }
  return result;
}

export default function CustomModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const { t } = useTranslation();
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.CUSTOM,
      existingLlmProvider
    ),
    provider: existingLlmProvider?.provider ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    model_configurations: existingLlmProvider?.model_configurations.map(
      (mc) => ({
        name: mc.name,
        display_name: mc.display_name ?? "",
        is_visible: mc.is_visible,
        max_input_tokens: mc.max_input_tokens ?? null,
        supports_image_input: mc.supports_image_input,
        supports_reasoning: mc.supports_reasoning,
        effectiveDisplayName: mc.effectiveDisplayName,
      })
    ) ?? [
      {
        name: "",
        display_name: "",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: false,
        supports_reasoning: false,
        effectiveDisplayName: "",
      },
    ],
    custom_config_list: existingLlmProvider?.custom_config
      ? Object.entries(existingLlmProvider.custom_config).map(
          ([key, value]) => ({ key, value: String(value) })
        )
      : [],
  };

  const modelConfigurationSchema = Yup.object({
    name: Yup.string().required(t("admin.custom_llm.model_name_required")),
    max_input_tokens: Yup.number()
      .transform((value, originalValue) =>
        originalValue === "" || originalValue === undefined ? null : value
      )
      .nullable()
      .optional(),
  });

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        provider: Yup.string().required(
          t("admin.custom_llm.provider_name_required")
        ),
        model_configurations: Yup.array(modelConfigurationSchema),
      })
    : Yup.object().shape({
        name: Yup.string().required(
          t("admin.custom_llm.display_name_required")
        ),
        provider: Yup.string().required(
          t("admin.custom_llm.provider_name_required")
        ),
        model_configurations: Yup.array(modelConfigurationSchema),
      });

  return (
    <ModalWrapper
      providerName={LLMProviderName.CUSTOM}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      description={t("admin.custom_llm.modal_desc")}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        setSubmitting(true);

        const modelConfigurations = values.model_configurations
          .filter((mc) => mc.name.trim() !== "")
          .map((mc) => ({
            name: mc.name,
            display_name: mc.display_name || undefined,
            is_visible: true,
            max_input_tokens: mc.max_input_tokens ?? null,
            supports_image_input: mc.supports_image_input,
            supports_reasoning: false,
            effectiveDisplayName: mc.display_name || mc.name,
          }));

        if (modelConfigurations.length === 0) {
          toast.error(t("admin.custom_llm.at_least_one_model"));
          setSubmitting(false);
          return;
        }

        // Always send custom_config as a dict (even empty) so the backend
        // preserves it as non-null — this is the signal that the provider was
        // created via CustomModal.
        const customConfig = keyValueListToDict(values.custom_config_list);

        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: (values as Record<string, unknown>).provider as string,
          values: {
            ...values,
            model_configurations: modelConfigurations,
            custom_config: customConfig,
          },
          initialValues: {
            ...initialValues,
            custom_config: keyValueListToDict(initialValues.custom_config_list),
          },
          existingLlmProvider,
          shouldMarkAsDefault,
          isCustomProvider: true,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? t("admin.custom_llm.provider_updated")
                  : t("admin.custom_llm.provider_enabled")
              );
            }
          },
        });
      }}
    >
      <InputPadder>
        <InputVertical
          withLabel="provider"
          title={t("admin.custom_llm.provider_label")}
          subDescription={markdown(t("admin.custom_llm.provider_desc"))}
        >
          <ProviderNameSelect disabled={!!existingLlmProvider} />
        </InputVertical>
      </InputPadder>

      <APIKeyField
        optional
        subDescription={t("admin.custom_llm.api_key_desc")}
      />

      <APIBaseField optional />

      <InputPadder>
        <InputVertical
          withLabel="api_version"
          title={t("admin.custom_llm.api_version_label")}
          suffix={t("admin.custom_llm.optional")}
        >
          <InputTypeInField name="api_version" />
        </InputVertical>
      </InputPadder>

      <InputPadder>
        <Section gap={0.75}>
          <Content
            title={t("admin.custom_llm.env_vars_title")}
            description={markdown(t("admin.custom_llm.env_vars_desc"))}
            width="full"
            variant="section"
            sizePreset="main-content"
          />

          <CustomConfigKeyValue />
        </Section>
      </InputPadder>

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <Section gap={0.5}>
        <InputPadder>
          <Content
            title={t("admin.custom_llm.models_title")}
            description={t("admin.custom_llm.models_desc")}
            variant="section"
            sizePreset="main-content"
            width="full"
          />
        </InputPadder>

        <Card padding="sm">
          <ModelConfigurationList />
        </Card>
      </Section>

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
