"use client";

import { useSWRConfig } from "swr";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import {
  BaseLLMFormValues,
  buildValidationSchema,
  useInitialValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  DisplayNameField,
  ModalWrapper,
  ModelAccessField,
  ModelSelectionField,
} from "@/sections/modals/languageModels/shared";
import { InputDivider, InputPadder, InputVertical } from "@opal/layouts";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import { toast } from "@/hooks/useToast";

export const MINIMAX_ENDPOINT_OPTIONS = [
  {
    name: "Global - Anthropic",
    value: "https://api.minimax.io/anthropic",
    description: "Recommended",
  },
  {
    name: "Global - OpenAI",
    value: "https://api.minimax.io/v1",
  },
  {
    name: "China - Anthropic",
    value: "https://api.minimaxi.com/anthropic",
  },
  {
    name: "China - OpenAI",
    value: "https://api.minimaxi.com/v1",
  },
] as const;

interface MiniMaxModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

function MiniMaxEndpointField() {
  return (
    <InputPadder>
      <InputVertical withLabel="api_base" title="API Endpoint">
        <InputSelectField name="api_base">
          <InputSelect.Trigger placeholder="Select an endpoint" />
          <InputSelect.Content>
            {MINIMAX_ENDPOINT_OPTIONS.map((option) => (
              <InputSelect.Item
                key={option.value}
                value={option.value}
                description={
                  "description" in option ? option.description : undefined
                }
              >
                {option.name}
              </InputSelect.Item>
            ))}
          </InputSelect.Content>
        </InputSelectField>
      </InputVertical>
    </InputPadder>
  );
}

export default function MiniMaxModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
  analyticsSource,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const onClose = () => onOpenChange?.(false);

  const baseInitialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.MINIMAX,
    existingLlmProvider
  );
  const initialValues: MiniMaxModalValues = {
    ...baseInitialValues,
    api_key: baseInitialValues.api_key ?? "",
    api_base: baseInitialValues.api_base ?? MINIMAX_ENDPOINT_OPTIONS[0].value,
  };

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiKey: true,
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.MINIMAX}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      description="Connect to MiniMax through an official API endpoint."
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
          providerName: LLMProviderName.MINIMAX,
          values,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
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
      <MiniMaxEndpointField />

      <APIKeyField providerName="MiniMax" />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
