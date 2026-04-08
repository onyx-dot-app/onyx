"use client";

import { useSWRConfig } from "swr";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import {
  useInitialValues,
  buildValidationSchema,
} from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import {
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import * as InputLayouts from "@/layouts/input-layouts";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { toast } from "@/hooks/useToast";

export default function OpenAIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onboardingState,
  onboardingActions,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.OPENAI,
    existingLlmProvider
  );

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.OPENAI}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          providerName: LLMProviderName.OPENAI,
          values,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault: isOnboarding
            ? (onboardingState?.data.llmProviders ?? []).length === 0
            : shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (isOnboarding && onboardingActions) {
              onboardingActions.updateData({
                llmProviders: [
                  ...(onboardingState?.data.llmProviders ?? []),
                  LLMProviderName.OPENAI,
                ],
              });
              onboardingActions.setButtonActive(true);
            } else {
              await refreshLlmProviderCaches(mutate);
              if (!existingLlmProvider) {
                toast.success("Provider enabled successfully!");
              } else {
                toast.success("Provider updated successfully!");
              }
            }
          },
        });
      }}
    >
      <APIKeyField providerName="OpenAI" />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
