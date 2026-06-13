"use client";

import { useMemo } from "react";
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
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  APIKeyField,
  APIBaseField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { useCustomProviderNames } from "@/hooks/useLanguageModels";
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
  return (
    <>
      <InputTypeIn
        placeholder="模型名称"
        value={model.name}
        onChange={(e) => onChange({ ...model, name: e.target.value })}
      />
      <InputTypeIn
        placeholder="显示名称"
        value={model.display_name}
        onChange={(e) => onChange({ ...model, display_name: e.target.value })}
      />
      <InputSelect
        value={model.supports_image_input ? "text-image" : "text-only"}
        onValueChange={(value) =>
          onChange({ ...model, supports_image_input: value === "text-image" })
        }
      >
        <InputSelect.Trigger placeholder="输入类型" />
        <InputSelect.Content>
          <InputSelect.Item value="text-only">仅文本</InputSelect.Item>
          <InputSelect.Item value="text-image">文本和图片</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
      <InputTypeIn
        placeholder="默认"
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
            <Text mainUiAction>模型名称</Text>
          </div>
          <Text mainUiAction>显示名称</Text>
          <Text mainUiAction>输入类型</Text>
          <Text mainUiAction>最大 Token 数</Text>
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
        <EmptyMessageCard title="尚未添加模型。" padding="sm" />
      )}

      <Button
        prominence="secondary"
        icon={SvgPlusCircle}
        onClick={handleAdd}
        type="button"
      >
        添加模型
      </Button>
    </div>
  );
}

function CustomConfigKeyValue() {
  const formikProps = useFormikContext<{ custom_config_list: KeyValue[] }>();
  return (
    <KeyValueInput
      items={formikProps.values.custom_config_list}
      keyPlaceholder="e.g. OPENAI_ORGANIZATION"
      onChange={(items) =>
        formikProps.setFieldValue("custom_config_list", items)
      }
      addButtonLabel="添加一行"
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
      placeholder="LiteLLM 中显示的服务商 ID 字符串"
      disabled={disabled}
      createPrefix="使用"
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
    name: Yup.string().required("请输入模型名称"),
    max_input_tokens: Yup.number()
      .transform((value, originalValue) =>
        originalValue === "" || originalValue === undefined ? null : value
      )
      .nullable()
      .optional(),
  });

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        provider: Yup.string().required("请输入服务商名称"),
        model_configurations: Yup.array(modelConfigurationSchema),
      })
    : Yup.object().shape({
        name: Yup.string().required("请输入显示名称"),
        provider: Yup.string().required("请输入服务商名称"),
        model_configurations: Yup.array(modelConfigurationSchema),
      });

  return (
    <ModalWrapper
      providerName={LLMProviderName.CUSTOM}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      description="连接来自其他 LiteLLM 兼容服务商的模型。"
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
          toast.error("请至少填写一个模型名称");
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
                  ? "服务商已更新！"
                  : "服务商已启用！"
              );
            }
          },
        });
      }}
    >
      <InputPadder>
        <InputVertical
          withLabel="provider"
          title="服务商"
          subDescription={markdown(
            "支持的 LLM 服务商完整列表请查看 [LiteLLM](https://docs.litellm.ai/docs/providers)。"
          )}
        >
          <ProviderNameSelect disabled={!!existingLlmProvider} />
        </InputVertical>
      </InputPadder>

      <APIKeyField
        optional
        subDescription="如果模型服务商需要认证，请粘贴 API Key。"
      />

      <APIBaseField optional />

      <InputPadder>
        <InputVertical
          withLabel="api_version"
          title="API Version"
          suffix="可选"
        >
          <InputTypeInField name="api_version" />
        </InputVertical>
      </InputPadder>

      <InputPadder>
        <Section gap={0.75}>
          <Content
            title="环境变量"
            description={markdown(
              "按模型服务商要求添加额外属性。这些属性会作为[环境变量](https://docs.litellm.ai/docs/set_keys#environment-variables)传递给 LiteLLM 的 `completion()` 调用。更多说明请查看[文档](https://docs.glomi.ai/admins/ai_models/custom_inference_provider)。"
            )}
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
            title="模型"
            description="列出你希望使用的 LLM 模型及其配置。模型完整列表请查看 LiteLLM。"
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
