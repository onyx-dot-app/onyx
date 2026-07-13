"use client";

import { useEffect, useRef } from "react";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider } from "@opal/layouts";
import { Tabs, Text, Button } from "@opal/components";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  PortkeyApiMode,
} from "@/lib/languageModels/types";
import { fetchPortkeyModels } from "@/lib/languageModels/svc";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  mergeFetchedModelConfigurations,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIBaseField,
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

// The two OpenAI-compatible surfaces (Chat Completions, Responses) hit /v1; the
// Anthropic-compatible Messages surface uses the bare host (LiteLLM appends
// /v1/messages).
const DEFAULT_API_BASE_OPENAI = "https://api.portkey.ai/v1";
const DEFAULT_API_BASE_ANTHROPIC = "https://api.portkey.ai";
const DEFAULT_API_MODE: PortkeyApiMode = "chat_completions";
const PORTKEY_API_MODE_KEY = "portkey_api_mode";
const DEFAULT_DISPLAY_NAME = "Portkey Gateway";

// Bases we consider "not customized" — switching modes replaces one of these
// with the new mode's default, but leaves a user-entered self-hosted base alone.
const KNOWN_DEFAULT_BASES = new Set<string>([
  DEFAULT_API_BASE_OPENAI,
  DEFAULT_API_BASE_ANTHROPIC,
  "",
]);

function defaultBaseForMode(mode: PortkeyApiMode): string {
  return mode === "messages"
    ? DEFAULT_API_BASE_ANTHROPIC
    : DEFAULT_API_BASE_OPENAI;
}

const API_MODE_TABS: {
  value: PortkeyApiMode;
  title: string;
  subtitle: string;
}[] = [
  {
    value: "chat_completions",
    title: "Chat Completions API",
    subtitle: "OpenAI-compatible",
  },
  { value: "responses", title: "Responses API", subtitle: "OpenAI-compatible" },
  { value: "messages", title: "Messages API", subtitle: "Anthropic-compatible" },
];

interface PortkeyModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface PortkeyModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function PortkeyModalInternals({
  existingLlmProvider,
  isOnboarding,
}: PortkeyModalInternalsProps) {
  const formikProps = useFormikContext<PortkeyModalValues>();
  const { setFieldValue, values } = formikProps;

  const mode =
    (values.custom_config?.[PORTKEY_API_MODE_KEY] as PortkeyApiMode | undefined) ??
    DEFAULT_API_MODE;
  const modeDefaultBase = defaultBaseForMode(mode);
  const isFetchDisabled = !values.api_base;
  const isBaseDefault = values.api_base === modeDefaultBase;

  const handleModeChange = (next: PortkeyApiMode) => {
    setFieldValue("custom_config", { [PORTKEY_API_MODE_KEY]: next });
    // Only swap the base URL if the user hasn't entered a custom (self-hosted) one.
    if (KNOWN_DEFAULT_BASES.has(values.api_base)) {
      setFieldValue("api_base", defaultBaseForMode(next));
    }
  };

  const handleFetchModels = async () => {
    const { models, error } = await fetchPortkeyModels({
      api_base: values.api_base,
      api_key: values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    setFieldValue(
      "model_configurations",
      mergeFetchedModelConfigurations(models, values.model_configurations)
    );
  };

  // When editing a saved provider the models load from the DB; refetch once on
  // open so the picker matches the "add" view. Best-effort — ignore errors so
  // the modal still works if the gateway is unreachable.
  const autoRefetched = useRef(false);
  useEffect(() => {
    if (autoRefetched.current || !existingLlmProvider?.id) return;
    if (!values.api_base) return;
    autoRefetched.current = true;
    fetchPortkeyModels({
      api_base: values.api_base,
      api_key: values.api_key || undefined,
      provider_id: existingLlmProvider.id,
    })
      .then(({ models }) => {
        if (models.length > 0) {
          setFieldValue(
            "model_configurations",
            mergeFetchedModelConfigurations(models, values.model_configurations)
          );
        }
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <Tabs
        value={mode}
        onValueChange={(next) => handleModeChange(next as PortkeyApiMode)}
      >
        <Tabs.List>
          {API_MODE_TABS.map((tab) => (
            <Tabs.Trigger key={tab.value} value={tab.value}>
              <div className="flex flex-col items-start">
                <Text font="main-ui-action" color="inherit">
                  {tab.title}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {tab.subtitle}
                </Text>
              </div>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs>

      <APIBaseField
        subDescription="Use Portkey's base URL or paste your self-hosted gateway base URL."
        placeholder={modeDefaultBase}
      />
      {!isBaseDefault && (
        <Button
          prominence="tertiary"
          size="xs"
          onClick={() => setFieldValue("api_base", modeDefaultBase)}
        >
          Restore default
        </Button>
      )}

      <APIKeyField
        subDescription={markdown(
          "Paste your API key from [Portkey](https://portkey.ai/) to load the available models."
        )}
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={false}
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function PortkeyModal({
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

  const initialValues: PortkeyModalValues = useInitialValues(
    isOnboarding,
    LLMProviderName.PORTKEY,
    existingLlmProvider
  ) as PortkeyModalValues;

  // The selected API mode round-trips through custom_config. useInitialValues
  // does not populate custom_config, so seed it here (mirroring CustomModal) so
  // submitProvider's custom_config_changed diff is accurate.
  const initialMode =
    (existingLlmProvider?.custom_config?.[PORTKEY_API_MODE_KEY] as
      | PortkeyApiMode
      | undefined) ?? DEFAULT_API_MODE;
  initialValues.custom_config = { [PORTKEY_API_MODE_KEY]: initialMode };

  if (!initialValues.api_base) {
    initialValues.api_base = defaultBaseForMode(initialMode);
  }
  if (!isOnboarding && !initialValues.name) {
    initialValues.name = DEFAULT_DISPLAY_NAME;
  }

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiBase: true,
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.PORTKEY}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
          providerName: LLMProviderName.PORTKEY,
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
      <PortkeyModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
