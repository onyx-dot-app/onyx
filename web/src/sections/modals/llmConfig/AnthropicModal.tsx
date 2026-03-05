import { Formik } from "formik";
import { LLMProviderFormProps } from "@/interfaces/llm";
import * as Yup from "yup";
import {
  ProviderFormEntrypointWrapper,
  ProviderFormContext,
} from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { LLMConfigurationModalWrapper } from "./shared";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  submitOnboardingProvider,
  buildOnboardingInitialValues,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import { SingleDefaultModelField } from "./components/SingleDefaultModelField";

export const ANTHROPIC_PROVIDER_NAME = "anthropic";
const DEFAULT_DEFAULT_MODEL_NAME = "claude-sonnet-4-5";

export function AnthropicModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";

  return (
    <ProviderFormEntrypointWrapper
      providerName="Anthropic"
      providerEndpoint={ANTHROPIC_PROVIDER_NAME}
      existingLlmProvider={existingLlmProvider}
      open={open}
      onOpenChange={onOpenChange}
      variant={variant}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
    >
      {({
        onClose,
        mutate,
        isTesting,
        setIsTesting,
        testError,
        setTestError,
        wellKnownLLMProvider,
        onboardingState: ctxOnboardingState,
        onboardingActions: ctxOnboardingActions,
      }: ProviderFormContext) => {
        const modelConfigurations = buildAvailableModelConfigurations(
          existingLlmProvider,
          wellKnownLLMProvider ?? llmDescriptor
        );

        const initialValues = isOnboarding
          ? {
              ...buildOnboardingInitialValues(),
              name: ANTHROPIC_PROVIDER_NAME,
              provider: ANTHROPIC_PROVIDER_NAME,
              api_key: "",
              default_model_name: DEFAULT_DEFAULT_MODEL_NAME,
            }
          : {
              ...buildDefaultInitialValues(
                existingLlmProvider,
                modelConfigurations
              ),
              api_key: existingLlmProvider?.api_key ?? "",
              api_base: existingLlmProvider?.api_base ?? undefined,
              default_model_name:
                wellKnownLLMProvider?.recommended_default_model?.name ??
                DEFAULT_DEFAULT_MODEL_NAME,
              is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
            };

        const validationSchema = isOnboarding
          ? Yup.object().shape({
              api_key: Yup.string().required("API Key is required"),
              default_model_name: Yup.string().required(
                "Model name is required"
              ),
            })
          : buildDefaultValidationSchema().shape({
              api_key: Yup.string().required("API Key is required"),
            });

        return (
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            validateOnMount={true}
            onSubmit={async (values, { setSubmitting }) => {
              if (isOnboarding && ctxOnboardingState && ctxOnboardingActions) {
                const modelConfigsToUse =
                  (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

                await submitOnboardingProvider({
                  providerName: ANTHROPIC_PROVIDER_NAME,
                  payload: {
                    ...values,
                    model_configurations: modelConfigsToUse,
                    is_auto_mode:
                      values.default_model_name === DEFAULT_DEFAULT_MODEL_NAME,
                  },
                  onboardingState: ctxOnboardingState,
                  onboardingActions: ctxOnboardingActions,
                  isCustomProvider: false,
                  onClose,
                  setIsSubmitting: setSubmitting,
                  setApiStatus: () => {},
                  setShowApiMessage: () => {},
                  setErrorMessage: (msg) => setTestError(msg),
                });
              } else {
                await submitLLMProvider({
                  providerName: ANTHROPIC_PROVIDER_NAME,
                  values,
                  initialValues,
                  modelConfigurations,
                  existingLlmProvider,
                  shouldMarkAsDefault,
                  setIsTesting,
                  setTestError,
                  mutate,
                  onClose,
                  setSubmitting,
                });
              }
            }}
          >
            {(formikProps) => (
              <LLMConfigurationModalWrapper
                providerEndpoint={ANTHROPIC_PROVIDER_NAME}
                existingProviderName={existingLlmProvider?.name}
                onClose={onClose}
                isFormValid={formikProps.isValid}
                isTesting={isTesting}
                testError={testError}
              >
                {!isOnboarding && (
                  <DisplayNameField disabled={!!existingLlmProvider} />
                )}

                <PasswordInputTypeInField name="api_key" label="API Key" />

                {isOnboarding ? (
                  <SingleDefaultModelField placeholder="E.g. claude-sonnet-4-5" />
                ) : (
                  <DisplayModels
                    modelConfigurations={modelConfigurations}
                    formikProps={formikProps}
                    recommendedDefaultModel={
                      wellKnownLLMProvider?.recommended_default_model ?? null
                    }
                    shouldShowAutoUpdateToggle={true}
                  />
                )}

                {!isOnboarding && <AdvancedOptions formikProps={formikProps} />}
              </LLMConfigurationModalWrapper>
            )}
          </Formik>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
