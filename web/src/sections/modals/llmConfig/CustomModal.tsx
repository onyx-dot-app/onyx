"use client";

import { useMemo } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import {
  LLMProviderFormProps,
  LLMProviderName,
  ModelConfiguration,
} from "@/interfaces/llm";
import * as Yup from "yup";
import { useInitialValues } from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  APIKeyField,
  APIBaseField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { useCustomProviderNames } from "@/hooks/useLLMProviders";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import KeyValueInput, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import { Button, Card, EmptyMessageCard } from "@opal/components";
import { SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import { markdown } from "@opal/utils";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { Content } from "@opal/layouts";
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
  return (
    <>
      <InputTypeIn
        placeholder="Model name"
        value={model.name}
        onChange={(e) => onChange({ ...model, name: e.target.value })}
        showClearButton={false}
      />
      <InputTypeIn
        placeholder="Display name"
        value={model.display_name}
        onChange={(e) => onChange({ ...model, display_name: e.target.value })}
        showClearButton={false}
      />
      <InputSelect
        value={model.supports_image_input ? "text-image" : "text-only"}
        onValueChange={(value) =>
          onChange({ ...model, supports_image_input: value === "text-image" })
        }
      >
        <InputSelect.Trigger placeholder="Input type" />
        <InputSelect.Content>
          <InputSelect.Item value="text-only">Text Only</InputSelect.Item>
          <InputSelect.Item value="text-image">Text & Image</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
      <InputTypeIn
        placeholder="Default"
        value={model.max_input_tokens?.toString() ?? ""}
        onChange={(e) =>
          onChange({
            ...model,
            max_input_tokens:
              e.target.value === "" ? null : Number(e.target.value),
          })
        }
        showClearButton={false}
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
            <Text mainUiAction>Model Name</Text>
          </div>
          <Text mainUiAction>Display Name</Text>
          <Text mainUiAction>Input Type</Text>
          <Text mainUiAction>Max Tokens</Text>
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
        <EmptyMessageCard title="No models added yet." padding="sm" />
      )}

      <Button
        prominence="secondary"
        icon={SvgPlusCircle}
        onClick={handleAdd}
        type="button"
      >
        Add Model
      </Button>
    </div>
  );
}

function CustomConfigKeyValue() {
  const formikProps = useFormikContext<{ custom_config_list: KeyValue[] }>();
  return (
    <KeyValueInput
      items={formikProps.values.custom_config_list}
      onChange={(items) =>
        formikProps.setFieldValue("custom_config_list", items)
      }
      addButtonLabel="Add Line"
    />
  );
}

// ─── Provider Name Select ─────────────────────────────────────────────────────

function ProviderNameSelect({ disabled }: { disabled?: boolean }) {
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
      placeholder="Select a provider"
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
      })
    ) ?? [
      {
        name: "",
        display_name: "",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: false,
        supports_reasoning: false,
      },
    ],
    custom_config_list: existingLlmProvider?.custom_config
      ? Object.entries(existingLlmProvider.custom_config).map(
          ([key, value]) => ({ key, value: String(value) })
        )
      : [],
  };

  const modelConfigurationSchema = Yup.object({
    name: Yup.string().required("Model name is required"),
    max_input_tokens: Yup.number()
      .transform((value, originalValue) =>
        originalValue === "" || originalValue === undefined ? null : value
      )
      .nullable()
      .optional(),
  });

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        provider: Yup.string().required("Provider Name is required"),
        model_configurations: Yup.array(modelConfigurationSchema),
      })
    : Yup.object().shape({
        name: Yup.string().required("Display Name is required"),
        provider: Yup.string().required("Provider Name is required"),
        model_configurations: Yup.array(modelConfigurationSchema),
      });

  return (
    <ModalWrapper
      providerName={LLMProviderName.CUSTOM}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
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
          }));

        if (modelConfigurations.length === 0) {
          toast.error("At least one model name is required");
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
                  ? "Provider updated successfully!"
                  : "Provider enabled successfully!"
              );
            }
          },
        });
      }}
    >
      <InputLayouts.FieldPadder>
        <InputLayouts.Vertical
          name="provider"
          title="Provider Name"
          subDescription={markdown(
            "Should be one of the providers listed at [LiteLLM](https://docs.litellm.ai/docs/providers)."
          )}
        >
          <ProviderNameSelect disabled={!!existingLlmProvider} />
        </InputLayouts.Vertical>
      </InputLayouts.FieldPadder>

      <APIBaseField optional />

      <InputLayouts.FieldPadder>
        <InputLayouts.Vertical
          name="api_version"
          title="API Version"
          suffix="optional"
        >
          <InputTypeInField name="api_version" />
        </InputLayouts.Vertical>
      </InputLayouts.FieldPadder>

      <APIKeyField
        optional
        subDescription="Paste your API key if your model provider requires authentication."
      />

      <InputLayouts.FieldPadder>
        <Section gap={0.75}>
          <Content
            title="Additional Configs"
            description={markdown(
              "Add extra properties as needed by the model provider. These are passed to LiteLLM's `completion()` call as [environment variables](https://docs.litellm.ai/docs/set_keys#environment-variables). See [documentation](https://docs.onyx.app/admins/ai_models/custom_inference_provider) for more instructions."
            )}
            widthVariant="full"
            variant="section"
            sizePreset="main-content"
          />

          <CustomConfigKeyValue />
        </Section>
      </InputLayouts.FieldPadder>

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <Section gap={0.5}>
        <InputLayouts.FieldPadder>
          <Content
            title="Models"
            description="List LLM models you wish to use and their configurations for this provider. See full list of models at LiteLLM."
            variant="section"
            sizePreset="main-content"
            widthVariant="full"
          />
        </InputLayouts.FieldPadder>

        <Card padding="sm">
          <ModelConfigurationList />
        </Card>
      </Section>

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
