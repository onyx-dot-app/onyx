import { useState, useEffect } from "react";
import { Form, Formik, FormikProps } from "formik";
import { SelectorFormField, TextFormField } from "@/components/Field";
import {
  LLMProviderFormProps,
  LLMProviderView,
  ModelConfiguration,
} from "../interfaces";
import * as Yup from "yup";
import {
  ProviderFormEntrypointWrapper,
  ProviderFormContext,
} from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import { FormActionButtons } from "./components/FormActionButtons";
import { FetchModelsButton } from "./components/FetchModelsButton";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  BaseLLMFormValues,
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import { fetchBedrockModels } from "../utils";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/refresh-components/tabs/tabs";
import { cn } from "@/lib/utils";

export const BEDROCK_PROVIDER_NAME = "bedrock";
const BEDROCK_DISPLAY_NAME = "AWS Bedrock";

// AWS Bedrock regions - kept in sync with backend
const AWS_REGION_OPTIONS = [
  { name: "us-east-1", value: "us-east-1" },
  { name: "us-east-2", value: "us-east-2" },
  { name: "us-west-2", value: "us-west-2" },
  { name: "us-gov-east-1", value: "us-gov-east-1" },
  { name: "us-gov-west-1", value: "us-gov-west-1" },
  { name: "ap-northeast-1", value: "ap-northeast-1" },
  { name: "ap-south-1", value: "ap-south-1" },
  { name: "ap-southeast-1", value: "ap-southeast-1" },
  { name: "ap-southeast-2", value: "ap-southeast-2" },
  { name: "ap-east-1", value: "ap-east-1" },
  { name: "ca-central-1", value: "ca-central-1" },
  { name: "eu-central-1", value: "eu-central-1" },
  { name: "eu-west-2", value: "eu-west-2" },
];

// Auth method values
const AUTH_METHOD_IAM = "iam";
const AUTH_METHOD_ACCESS_KEY = "access_key";
const AUTH_METHOD_LONG_TERM_API_KEY = "long_term_api_key";

// Field name constants
const FIELD_AWS_REGION_NAME = "custom_config.AWS_REGION_NAME";
const FIELD_BEDROCK_AUTH_METHOD = "custom_config.BEDROCK_AUTH_METHOD";
const FIELD_AWS_ACCESS_KEY_ID = "custom_config.AWS_ACCESS_KEY_ID";
const FIELD_AWS_SECRET_ACCESS_KEY = "custom_config.AWS_SECRET_ACCESS_KEY";
const FIELD_AWS_BEARER_TOKEN_BEDROCK = "custom_config.AWS_BEARER_TOKEN_BEDROCK";

interface BedrockFormValues extends BaseLLMFormValues {
  custom_config: {
    AWS_REGION_NAME: string;
    BEDROCK_AUTH_METHOD?: string;
    AWS_ACCESS_KEY_ID?: string;
    AWS_SECRET_ACCESS_KEY?: string;
    AWS_BEARER_TOKEN_BEDROCK?: string;
  };
}

interface BedrockFormInternalsProps {
  formikProps: FormikProps<BedrockFormValues>;
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  modelConfigurations: ModelConfiguration[];
  isTesting: boolean;
  testError: string;
  mutate: (key: string) => void;
  onClose: () => void;
}

function BedrockFormInternals({
  formikProps,
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  modelConfigurations,
  isTesting,
  testError,
  mutate,
  onClose,
}: BedrockFormInternalsProps) {
  const authMethod = formikProps.values.custom_config?.BEDROCK_AUTH_METHOD;

  // Clean up unused auth fields when tab changes
  useEffect(() => {
    if (authMethod === AUTH_METHOD_IAM) {
      // IAM role doesn't need any credentials
      formikProps.setFieldValue(FIELD_AWS_ACCESS_KEY_ID, "");
      formikProps.setFieldValue(FIELD_AWS_SECRET_ACCESS_KEY, "");
      formikProps.setFieldValue(FIELD_AWS_BEARER_TOKEN_BEDROCK, "");
    } else if (authMethod === AUTH_METHOD_ACCESS_KEY) {
      // Access key doesn't use bearer token
      formikProps.setFieldValue(FIELD_AWS_BEARER_TOKEN_BEDROCK, "");
    } else if (authMethod === AUTH_METHOD_LONG_TERM_API_KEY) {
      // Long-term API key doesn't use access key credentials
      formikProps.setFieldValue(FIELD_AWS_ACCESS_KEY_ID, "");
      formikProps.setFieldValue(FIELD_AWS_SECRET_ACCESS_KEY, "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authMethod]);

  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || modelConfigurations;

  // Check if auth credentials are complete
  const isAuthComplete =
    authMethod === AUTH_METHOD_IAM ||
    (authMethod === AUTH_METHOD_ACCESS_KEY &&
      formikProps.values.custom_config?.AWS_ACCESS_KEY_ID &&
      formikProps.values.custom_config?.AWS_SECRET_ACCESS_KEY) ||
    (authMethod === AUTH_METHOD_LONG_TERM_API_KEY &&
      formikProps.values.custom_config?.AWS_BEARER_TOKEN_BEDROCK);

  const isFetchDisabled =
    !formikProps.values.custom_config?.AWS_REGION_NAME || !isAuthComplete;

  return (
    <Form className={LLM_FORM_CLASS_NAME}>
      <DisplayNameField disabled={!!existingLlmProvider} />

      <SelectorFormField
        name={FIELD_AWS_REGION_NAME}
        label="AWS Region"
        subtext="Region where your Amazon Bedrock models are hosted."
        options={AWS_REGION_OPTIONS}
      />

      <div>
        <Text as="p" mainUiAction>
          Authentication Method
        </Text>
        <Text as="p" secondaryBody text03>
          Choose how Onyx should authenticate with Bedrock.
        </Text>
        <Tabs
          value={authMethod || AUTH_METHOD_ACCESS_KEY}
          onValueChange={(value) =>
            formikProps.setFieldValue(FIELD_BEDROCK_AUTH_METHOD, value)
          }
          className="mt-2"
        >
          <TabsList>
            <TabsTrigger value={AUTH_METHOD_IAM}>IAM Role</TabsTrigger>
            <TabsTrigger value={AUTH_METHOD_ACCESS_KEY}>Access Key</TabsTrigger>
            <TabsTrigger value={AUTH_METHOD_LONG_TERM_API_KEY}>
              Long-term API Key
            </TabsTrigger>
          </TabsList>

          <TabsContent
            value={AUTH_METHOD_IAM}
            className="data-[state=active]:animate-fade-in-scale"
          >
            <Text as="p" text03>
              Uses the IAM role attached to your AWS environment. Recommended
              for EC2, ECS, Lambda, or other AWS services.
            </Text>
          </TabsContent>

          <TabsContent
            value={AUTH_METHOD_ACCESS_KEY}
            className={cn(
              "data-[state=active]:animate-fade-in-scale",
              "mt-4 ml-2"
            )}
          >
            <div className="flex flex-col gap-4">
              <TextFormField
                name={FIELD_AWS_ACCESS_KEY_ID}
                label="AWS Access Key ID"
                placeholder="AKIAIOSFODNN7EXAMPLE"
              />
              <TextFormField
                name={FIELD_AWS_SECRET_ACCESS_KEY}
                label="AWS Secret Access Key"
                placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                type="password"
              />
            </div>
          </TabsContent>

          <TabsContent
            value={AUTH_METHOD_LONG_TERM_API_KEY}
            className={cn(
              "data-[state=active]:animate-fade-in-scale",
              "mt-4 ml-2"
            )}
          >
            <div className="flex flex-col gap-4">
              <TextFormField
                name={FIELD_AWS_BEARER_TOKEN_BEDROCK}
                label="AWS Bedrock Long-term API Key"
                placeholder="Your long-term API key"
                type="password"
              />
            </div>
          </TabsContent>
        </Tabs>
      </div>

      <FetchModelsButton
        onFetch={() =>
          fetchBedrockModels({
            aws_region_name:
              formikProps.values.custom_config?.AWS_REGION_NAME ?? "",
            aws_access_key_id:
              formikProps.values.custom_config?.AWS_ACCESS_KEY_ID,
            aws_secret_access_key:
              formikProps.values.custom_config?.AWS_SECRET_ACCESS_KEY,
            aws_bearer_token_bedrock:
              formikProps.values.custom_config?.AWS_BEARER_TOKEN_BEDROCK,
            provider_name: existingLlmProvider?.name,
          })
        }
        isDisabled={isFetchDisabled}
        disabledHint={
          !formikProps.values.custom_config?.AWS_REGION_NAME
            ? "Select an AWS region."
            : !isAuthComplete
              ? 'Complete the "Authentication Method" section.'
              : undefined
        }
        onModelsFetched={setFetchedModels}
        autoFetchOnInitialLoad={!!existingLlmProvider}
      />

      <Separator />

      <DisplayModels
        modelConfigurations={currentModels}
        formikProps={formikProps}
        noModelConfigurationsMessage={
          "Fetch available models first, then you'll be able to select " +
          "the models you want to make available in Onyx."
        }
        recommendedDefaultModel={null}
        shouldShowAutoUpdateToggle={false}
      />

      <Separator />

      <AdvancedOptions formikProps={formikProps} />

      <FormActionButtons
        isTesting={isTesting}
        testError={testError}
        existingLlmProvider={existingLlmProvider}
        mutate={mutate}
        onClose={onClose}
        isFormValid={formikProps.isValid}
      />
    </Form>
  );
}

export function BedrockForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);

  return (
    <ProviderFormEntrypointWrapper
      providerName={BEDROCK_DISPLAY_NAME}
      existingLlmProvider={existingLlmProvider}
    >
      {({
        onClose,
        mutate,
        popup,
        setPopup,
        isTesting,
        setIsTesting,
        testError,
        setTestError,
        wellKnownLLMProvider,
      }: ProviderFormContext) => {
        const modelConfigurations = buildAvailableModelConfigurations(
          existingLlmProvider,
          wellKnownLLMProvider
        );
        const initialValues: BedrockFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          custom_config: {
            AWS_REGION_NAME:
              (existingLlmProvider?.custom_config?.AWS_REGION_NAME as string) ??
              "",
            BEDROCK_AUTH_METHOD:
              (existingLlmProvider?.custom_config
                ?.BEDROCK_AUTH_METHOD as string) ?? "access_key",
            AWS_ACCESS_KEY_ID:
              (existingLlmProvider?.custom_config
                ?.AWS_ACCESS_KEY_ID as string) ?? "",
            AWS_SECRET_ACCESS_KEY:
              (existingLlmProvider?.custom_config
                ?.AWS_SECRET_ACCESS_KEY as string) ?? "",
            AWS_BEARER_TOKEN_BEDROCK:
              (existingLlmProvider?.custom_config
                ?.AWS_BEARER_TOKEN_BEDROCK as string) ?? "",
          },
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          custom_config: Yup.object({
            AWS_REGION_NAME: Yup.string().required("AWS Region is required"),
          }),
        });

        return (
          <>
            {popup}
            <Formik
              initialValues={initialValues}
              validationSchema={validationSchema}
              validateOnMount={true}
              onSubmit={async (values, { setSubmitting }) => {
                // Filter out empty custom_config values
                const filteredCustomConfig = Object.fromEntries(
                  Object.entries(values.custom_config || {}).filter(
                    ([, v]) => v !== ""
                  )
                );

                const submitValues = {
                  ...values,
                  custom_config:
                    Object.keys(filteredCustomConfig).length > 0
                      ? filteredCustomConfig
                      : undefined,
                };

                await submitLLMProvider({
                  providerName: BEDROCK_PROVIDER_NAME,
                  values: submitValues,
                  initialValues,
                  modelConfigurations:
                    fetchedModels.length > 0
                      ? fetchedModels
                      : modelConfigurations,
                  existingLlmProvider,
                  shouldMarkAsDefault,
                  setIsTesting,
                  setTestError,
                  setPopup,
                  mutate,
                  onClose,
                  setSubmitting,
                });
              }}
            >
              {(formikProps) => (
                <BedrockFormInternals
                  formikProps={formikProps}
                  existingLlmProvider={existingLlmProvider}
                  fetchedModels={fetchedModels}
                  setFetchedModels={setFetchedModels}
                  modelConfigurations={modelConfigurations}
                  isTesting={isTesting}
                  testError={testError}
                  mutate={mutate}
                  onClose={onClose}
                />
              )}
            </Formik>
          </>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
