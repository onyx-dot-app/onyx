"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import type { ModelConfiguration } from "@/lib/languageModels/types";
import * as Yup from "yup";
import {
  clampModelSettings,
  useInitialValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  APIBaseField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
  useApiBaseSubDescription,
} from "@/sections/modals/languageModels/shared";
import { ModelSettingsPopover } from "@/sections/modals/languageModels/ModelSettingsPopover";
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
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import {
  Content,
  InputDivider,
  InputPadder,
  InputVertical,
  toast,
} from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";

// ─── Model Configuration List ─────────────────────────────────────────────────

const MODEL_GRID_COLS =
  "grid-cols-[2fr_2fr_minmax(10rem,1fr)_1fr_2.25rem_2.25rem]";

type CustomModelConfiguration = Pick<
  ModelConfiguration,
  | "name"
  | "max_input_tokens"
  | "supports_image_input"
  | "supports_reasoning"
  | "supported_reasoning_efforts"
  | "reasoning_effort_max"
  | "reasoning_effort_default"
  | "temperature_default"
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
  const t = useTranslations("admin.languageModels.modals");
  return (
    <>
      <InputTypeIn
        placeholder={t("custom.modelRow.namePlaceholder")}
        value={model.name}
        onChange={(e) => onChange({ ...model, name: e.target.value })}
      />
      <InputTypeIn
        placeholder={t("custom.modelRow.displayNamePlaceholder")}
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
          placeholder={t("custom.modelRow.inputTypePlaceholder")}
        />
        <InputSelect.Content>
          <InputSelect.Item value="text-only">
            {t("custom.modelRow.textOnly.label")}
          </InputSelect.Item>
          <InputSelect.Item value="text-image">
            {t("custom.modelRow.textImage.label")}
          </InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
      <InputTypeIn
        placeholder={t("custom.modelRow.maxTokensPlaceholder")}
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
      <ModelSettingsPopover
        model={model}
        onChange={(patch) => onChange({ ...model, ...patch })}
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
  const t = useTranslations("admin.languageModels.modals");
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
        supports_reasoning: false,
      },
    ]);
  }

  return (
    <div className="w-full flex flex-col gap-y-2">
      {models.length > 0 ? (
        <div className={`grid items-center gap-1 ${MODEL_GRID_COLS}`}>
          <div className="pb-1">
            <Text mainUiAction>{t("custom.modelTable.name.header")}</Text>
          </div>
          <Text mainUiAction>{t("custom.modelTable.displayName.header")}</Text>
          <Text mainUiAction>{t("custom.modelTable.inputType.header")}</Text>
          <Text mainUiAction>{t("custom.modelTable.maxTokens.header")}</Text>
          <div aria-hidden />
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
        <EmptyMessageCard title={t("custom.models.empty.title")} padding={2} />
      )}

      <Button
        prominence="secondary"
        icon={SvgPlusCircle}
        onClick={handleAdd}
        type="button"
      >
        {t("custom.addModelButton.label")}
      </Button>
    </div>
  );
}

function CustomConfigKeyValue() {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<{ custom_config_list: KeyValue[] }>();
  return (
    <KeyValueInput
      items={formikProps.values.custom_config_list}
      keyPlaceholder="e.g. OPENAI_ORGANIZATION"
      onChange={(items) =>
        formikProps.setFieldValue("custom_config_list", items)
      }
      addButtonLabel={t("custom.envVars.addButton.label")}
    />
  );
}

// ─── Provider Name Select ─────────────────────────────────────────────────────

function ProviderNameSelect({ disabled }: { disabled?: boolean }) {
  const t = useTranslations("admin.languageModels.modals");
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
      placeholder={t("custom.providerField.placeholder")}
      disabled={disabled}
      createPrefix={t("custom.providerField.createPrefix")}
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
  analyticsSource,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const apiBaseSubDescription = useApiBaseSubDescription();

  const onClose = () => onOpenChange?.(false);

  const initialValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.CUSTOM,
      existingLlmProvider
    ),
    provider: existingLlmProvider?.provider ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    model_configurations: existingLlmProvider?.model_configurations.map((mc) =>
      // Stored policy can exceed a capability that shrank since the save,
      // and the API rejects such values on submit.
      clampModelSettings({
        name: mc.name,
        display_name: mc.display_name ?? "",
        is_visible: mc.is_visible,
        max_input_tokens: mc.max_input_tokens ?? null,
        supports_image_input: mc.supports_image_input,
        supports_reasoning: mc.supports_reasoning,
        supported_reasoning_efforts: mc.supported_reasoning_efforts,
        reasoning_effort_max: mc.reasoning_effort_max,
        reasoning_effort_default: mc.reasoning_effort_default,
        temperature_default: mc.temperature_default,
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
        supported_reasoning_efforts: undefined,
        reasoning_effort_max: null,
        reasoning_effort_default: null,
        temperature_default: null,
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
    name: Yup.string().required(t("validation.modelNameRequired")),
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
          t("custom.validation.providerNameRequired")
        ),
        model_configurations: Yup.array(modelConfigurationSchema),
      })
    : Yup.object().shape({
        name: Yup.string().required(t("custom.validation.displayNameRequired")),
        provider: Yup.string().required(
          t("custom.validation.providerNameRequired")
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
      description={t("custom.description")}
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
            supports_reasoning: mc.supports_reasoning,
            supported_reasoning_efforts: mc.supported_reasoning_efforts,
            reasoning_effort_max: mc.reasoning_effort_max,
            reasoning_effort_default: mc.reasoning_effort_default,
            temperature_default: mc.temperature_default,
            effectiveDisplayName: mc.display_name || mc.name,
          }));

        if (modelConfigurations.length === 0) {
          toast.error(t("custom.toasts.modelNameRequired"));
          setSubmitting(false);
          return;
        }

        // Always send custom_config as a dict (even empty) so the backend
        // preserves it as non-null — this is the signal that the provider was
        // created via CustomModal.
        const customConfig = keyValueListToDict(values.custom_config_list);

        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
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
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <InputPadder>
        <InputVertical
          withLabel="provider"
          title={t("custom.providerField.title")}
          subDescription={markdown(t("custom.providerField.description"))}
        >
          <ProviderNameSelect disabled={!!existingLlmProvider} />
        </InputVertical>
      </InputPadder>

      <APIKeyField
        optional
        subDescription={t("custom.apiKeyField.description")}
      />

      <APIBaseField optional subDescription={apiBaseSubDescription} />

      <InputPadder>
        <InputVertical
          withLabel="api_version"
          title={t("custom.apiVersionField.title")}
          suffix={t("setup.optionalSuffix.label")}
        >
          <InputTypeInField name="api_version" />
        </InputVertical>
      </InputPadder>

      <InputPadder>
        <Section gap={3}>
          <Content
            title={t("custom.envVars.title")}
            description={markdown(t("custom.envVars.description"))}
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
      <Section gap={2}>
        <InputPadder>
          <Content
            title={t("custom.models.title")}
            description={t("custom.models.description")}
            variant="section"
            sizePreset="main-content"
            width="full"
          />
        </InputPadder>

        <Card padding={2}>
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
