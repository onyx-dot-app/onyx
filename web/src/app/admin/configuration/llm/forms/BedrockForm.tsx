import { Form, Formik } from "formik";
import {
  SelectorFormField,
  TextFormField,
  Label,
  SubLabel,
} from "@/components/Field";
import { LLMProviderView, ModelConfiguration } from "../interfaces";
import * as Yup from "yup";
import {
  ProviderFormEntrypointWrapper,
  ProviderFormContext,
} from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import { FormActionButtons } from "./components/FormActionButtons";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  submitLLMProvider,
  BaseLLMFormValues,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import Separator from "@/refresh-components/Separator";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { LoadingAnimation } from "@/components/Loading";
import { useEffect, useState } from "react";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/refresh-components/tabs/tabs";
import { cn } from "@/lib/utils";

export const BEDROCK_PROVIDER_NAME = "bedrock";
const BEDROCK_DISPLAY_NAME = "AWS Bedrock";
const BEDROCK_MODELS_API_URL = "/api/admin/llm/bedrock/available-models";

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

interface BedrockFormValues extends BaseLLMFormValues {
  custom_config: {
    AWS_REGION_NAME: string;
    BEDROCK_AUTH_METHOD?: string;
    AWS_ACCESS_KEY_ID?: string;
    AWS_SECRET_ACCESS_KEY?: string;
    AWS_BEARER_TOKEN_BEDROCK?: string;
  };
}

interface BedrockFormProps {
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
}

interface BedrockModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number;
  supports_image_input: boolean;
}

export function BedrockForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: BedrockFormProps) {
  const [availableModels, setAvailableModels] = useState<ModelConfiguration[]>(
    []
  );
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [fetchModelsError, setFetchModelsError] = useState<string>("");

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
        modelConfigurations,
      }: ProviderFormContext) => {
        const initialValues: BedrockFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            availableModels.length > 0 ? availableModels : modelConfigurations
          ),
          default_model_name: existingLlmProvider?.default_model_name ?? "",
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

        const fetchModels = async (regionName: string) => {
          if (!regionName) {
            setFetchModelsError("AWS region is required to fetch models");
            return;
          }

          setIsLoadingModels(true);
          setFetchModelsError("");

          try {
            const response = await fetch(BEDROCK_MODELS_API_URL, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                aws_region_name: regionName,
                provider_name: existingLlmProvider?.name,
              }),
            });

            if (!response.ok) {
              let errorMessage = "Failed to fetch models";
              try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
              } catch {
                // ignore JSON parsing errors
              }
              throw new Error(errorMessage);
            }

            const data: BedrockModelResponse[] = await response.json();
            const models: ModelConfiguration[] = data.map((model) => ({
              name: model.name,
              display_name: model.display_name,
              is_visible: true,
              max_input_tokens: model.max_input_tokens,
              supports_image_input: model.supports_image_input,
            }));

            setAvailableModels(models);
            setPopup({
              message: `Successfully fetched ${models.length} models for the selected region.`,
              type: "success",
            });
          } catch (error) {
            const errorMessage =
              error instanceof Error ? error.message : "Unknown error";
            setFetchModelsError(errorMessage);
            setPopup({
              message: `Failed to fetch models: ${errorMessage}`,
              type: "error",
            });
          } finally {
            setIsLoadingModels(false);
          }
        };

        return (
          <>
            {popup}
            <Formik
              initialValues={initialValues}
              validationSchema={validationSchema}
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
                    availableModels.length > 0
                      ? availableModels
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
              {(formikProps) => {
                const authMethod =
                  formikProps.values.custom_config?.BEDROCK_AUTH_METHOD;

                // Auto-fetch models when editing an existing provider
                useEffect(() => {
                  if (
                    existingLlmProvider &&
                    formikProps.values.custom_config?.AWS_REGION_NAME &&
                    availableModels.length === 0
                  ) {
                    fetchModels(
                      formikProps.values.custom_config.AWS_REGION_NAME
                    );
                  }
                }, []);

                const currentModels =
                  availableModels.length > 0
                    ? availableModels
                    : modelConfigurations;

                return (
                  <Form className="gap-y-4 items-stretch mt-6">
                    <DisplayNameField disabled={!!existingLlmProvider} />

                    <SelectorFormField
                      name="custom_config.AWS_REGION_NAME"
                      label="AWS Region"
                      subtext="Region where your Amazon Bedrock models are hosted."
                      options={AWS_REGION_OPTIONS}
                    />

                    <div>
                      <Label>Authentication Method</Label>
                      <SubLabel>
                        Choose how Onyx should authenticate with Bedrock.
                      </SubLabel>
                      <Tabs
                        value={authMethod || AUTH_METHOD_ACCESS_KEY}
                        onValueChange={(value) =>
                          formikProps.setFieldValue(
                            "custom_config.BEDROCK_AUTH_METHOD",
                            value
                          )
                        }
                        className="mt-2"
                      >
                        <TabsList>
                          <TabsTrigger value={AUTH_METHOD_IAM}>
                            IAM Role
                          </TabsTrigger>
                          <TabsTrigger value={AUTH_METHOD_ACCESS_KEY}>
                            Access Key
                          </TabsTrigger>
                          <TabsTrigger value={AUTH_METHOD_LONG_TERM_API_KEY}>
                            Long-term API Key
                          </TabsTrigger>
                        </TabsList>

                        <TabsContent
                          value={AUTH_METHOD_IAM}
                          className="data-[state=active]:animate-fade-in-scale"
                        >
                          <Text text03>
                            Uses the IAM role attached to your AWS environment.
                            Recommended for EC2, ECS, Lambda, or other AWS
                            services.
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
                              name="custom_config.AWS_ACCESS_KEY_ID"
                              label="AWS Access Key ID"
                              placeholder="AKIAIOSFODNN7EXAMPLE"
                            />
                            <TextFormField
                              name="custom_config.AWS_SECRET_ACCESS_KEY"
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
                              name="custom_config.AWS_BEARER_TOKEN_BEDROCK"
                              label="AWS Bedrock Long-term API Key"
                              placeholder="Your long-term API key"
                              type="password"
                            />
                          </div>
                        </TabsContent>
                      </Tabs>
                    </div>

                    <Separator />

                    <div className="flex flex-col gap-2">
                      <Button
                        type="button"
                        onClick={() =>
                          fetchModels(
                            formikProps.values.custom_config?.AWS_REGION_NAME ||
                              ""
                          )
                        }
                        disabled={
                          isLoadingModels ||
                          !formikProps.values.custom_config?.AWS_REGION_NAME
                        }
                        className="w-fit"
                      >
                        {isLoadingModels ? (
                          <Text>
                            <LoadingAnimation text="Fetching models" />
                          </Text>
                        ) : (
                          "Fetch Available Models"
                        )}
                      </Button>

                      {fetchModelsError && (
                        <Text className="text-red-600 text-sm">
                          {fetchModelsError}
                        </Text>
                      )}

                      <Text className="text-sm text-gray-600">
                        Retrieve the latest available models for this region
                        (including cross-region inference models).
                      </Text>
                    </div>

                    <DisplayModels
                      modelConfigurations={currentModels}
                      formikProps={formikProps}
                      noModelConfigurationsMessage="No models found. Please select a region and fetch available models."
                      isLoading={isLoadingModels}
                    />

                    <Separator />

                    <AdvancedOptions
                      currentModelConfigurations={currentModels}
                      formikProps={formikProps}
                    />

                    <FormActionButtons
                      isTesting={isTesting}
                      testError={testError}
                      existingLlmProvider={existingLlmProvider}
                      mutate={mutate}
                      onClose={onClose}
                    />
                  </Form>
                );
              }}
            </Formik>
          </>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
