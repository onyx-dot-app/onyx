import Separator from "@/refresh-components/Separator";
import {
  ArrayHelpers,
  Field,
  FieldArray,
  Form,
  Formik,
  ErrorMessage,
} from "formik";
import { LLMProviderFormProps, LLMProviderView } from "../interfaces";
import * as Yup from "yup";
import { ProviderFormEntrypointWrapper } from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import { ApiKeyField } from "./components/ApiKeyField";
import { FormActionButtons } from "./components/FormActionButtons";
import {
  submitLLMProvider,
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { TextFormField } from "@/components/Field";
import { ModelConfigurationField } from "../ModelConfigurationField";
import Text from "@/refresh-components/texts/Text";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgX } from "@opal/icons";

export const CUSTOM_PROVIDER_NAME = "custom";

function customConfigProcessing(customConfigsList: [string, string][]) {
  const customConfig: { [key: string]: string } = {};
  customConfigsList.forEach(([key, value]) => {
    customConfig[key] = value;
  });
  return customConfig;
}

export function CustomForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="Custom LLM"
      existingLlmProvider={existingLlmProvider}
      buttonMode={!existingLlmProvider}
      buttonText="Add Custom LLM Provider"
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
      }) => {
        const initialValues = {
          ...buildDefaultInitialValues(existingLlmProvider),
          provider: existingLlmProvider?.provider ?? "",
          api_key: existingLlmProvider?.api_key ?? "",
          api_base: existingLlmProvider?.api_base ?? "",
          api_version: existingLlmProvider?.api_version ?? "",
          model_configurations: existingLlmProvider?.model_configurations.map(
            (modelConfiguration) => ({
              ...modelConfiguration,
              max_input_tokens: modelConfiguration.max_input_tokens ?? null,
            })
          ) ?? [{ name: "", is_visible: true, max_input_tokens: null }],
          custom_config_list: existingLlmProvider?.custom_config
            ? Object.entries(existingLlmProvider.custom_config)
            : [],
          deployment_name: existingLlmProvider?.deployment_name ?? null,
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          provider: Yup.string().required("Provider Name is required"),
          api_key: Yup.string(),
          api_base: Yup.string(),
          api_version: Yup.string(),
          model_configurations: Yup.array(
            Yup.object({
              name: Yup.string().required("Model name is required"),
              is_visible: Yup.boolean().required("Visibility is required"),
              max_input_tokens: Yup.number()
                .transform((value, originalValue) =>
                  originalValue === "" || originalValue === undefined
                    ? null
                    : value
                )
                .nullable()
                .optional(),
            })
          ),
          custom_config_list: Yup.array(),
          deployment_name: Yup.string().nullable(),
        });

        return (
          <>
            {popup}
            <Formik
              initialValues={initialValues}
              validationSchema={validationSchema}
              validateOnMount={true}
              onSubmit={async (values, { setSubmitting }) => {
                setSubmitting(true);

                // Build model configurations from the form
                const modelConfigurations = values.model_configurations
                  .map((mc) => ({
                    name: mc.name,
                    is_visible: mc.is_visible,
                    max_input_tokens: mc.max_input_tokens ?? null,
                    supports_image_input: null,
                  }))
                  .filter(
                    (mc) =>
                      mc.name === values.default_model_name || mc.is_visible
                  );

                if (modelConfigurations.length === 0) {
                  setPopup({
                    type: "error",
                    message: "At least one model name is required",
                  });
                  setSubmitting(false);
                  return;
                }

                await submitLLMProvider({
                  providerName: values.provider,
                  values: {
                    ...values,
                    custom_config: customConfigProcessing(
                      values.custom_config_list
                    ),
                  },
                  initialValues: {
                    ...initialValues,
                    custom_config: customConfigProcessing(
                      initialValues.custom_config_list
                    ),
                  },
                  modelConfigurations,
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
                return (
                  <Form className={LLM_FORM_CLASS_NAME}>
                    <DisplayNameField disabled={!!existingLlmProvider} />

                    <TextFormField
                      name="provider"
                      label="Provider Name"
                      subtext={
                        <>
                          Should be one of the providers listed at{" "}
                          <a
                            target="_blank"
                            href="https://docs.litellm.ai/docs/providers"
                            className="text-link"
                            rel="noreferrer"
                          >
                            https://docs.litellm.ai/docs/providers
                          </a>
                          .
                        </>
                      }
                      placeholder="Name of the custom provider"
                    />

                    <Separator />

                    <Text as="p" secondaryBody text03>
                      Fill in the following as needed. Refer to the LiteLLM
                      documentation for the provider specified above to
                      determine which fields are required.
                    </Text>

                    <ApiKeyField label="[Optional] API Key" />

                    <TextFormField
                      name="api_base"
                      label="[Optional] API Base"
                      placeholder="API Base URL"
                    />

                    <TextFormField
                      name="api_version"
                      label="[Optional] API Version"
                      placeholder="API Version"
                    />

                    <Separator />

                    <Text as="p" mainUiAction>
                      [Optional] Custom Configs
                    </Text>
                    <Text as="p" secondaryBody text03>
                      <div>
                        Additional configurations needed by the model provider.
                        These are passed to LiteLLM via environment variables
                        and as arguments into the completion call.
                      </div>
                      <div className="mt-2">
                        For example, when configuring the Cloudflare provider,
                        you would need to set CLOUDFLARE_ACCOUNT_ID as the key
                        and your Cloudflare account ID as the value.
                      </div>
                    </Text>

                    <FieldArray
                      name="custom_config_list"
                      render={(arrayHelpers: ArrayHelpers<any[]>) => (
                        <div className="w-full">
                          {formikProps.values.custom_config_list.map(
                            (_, index) => (
                              <div
                                key={index}
                                className={
                                  (index === 0 ? "mt-2" : "mt-6") + " w-full"
                                }
                              >
                                <div className="flex w-full">
                                  <div className="w-full mr-6 border border-border p-3 rounded">
                                    <div>
                                      <Text as="p" mainUiAction>
                                        Key
                                      </Text>
                                      <Field
                                        name={`custom_config_list[${index}][0]`}
                                        className="border border-border bg-background rounded w-full py-2 px-3 mr-4"
                                        autoComplete="off"
                                      />
                                      <ErrorMessage
                                        name={`custom_config_list[${index}][0]`}
                                        component="div"
                                        className="text-error text-sm mt-1"
                                      />
                                    </div>
                                    <div className="mt-3">
                                      <Text as="p" mainUiAction>
                                        Value
                                      </Text>
                                      <Field
                                        name={`custom_config_list[${index}][1]`}
                                        className="border border-border bg-background rounded w-full py-2 px-3 mr-4"
                                        autoComplete="off"
                                      />
                                      <ErrorMessage
                                        name={`custom_config_list[${index}][1]`}
                                        component="div"
                                        className="text-error text-sm mt-1"
                                      />
                                    </div>
                                  </div>
                                  <div className="my-auto">
                                    <IconButton
                                      icon={SvgX}
                                      className="my-auto"
                                      onClick={() => arrayHelpers.remove(index)}
                                      secondary
                                    />
                                  </div>
                                </div>
                              </div>
                            )
                          )}
                          <CreateButton
                            onClick={() => arrayHelpers.push(["", ""])}
                            className="mt-3"
                            type="button"
                          >
                            Add New
                          </CreateButton>
                        </div>
                      )}
                    />

                    <Separator />

                    <ModelConfigurationField
                      name="model_configurations"
                      formikProps={formikProps as any}
                    />

                    <Separator />

                    <TextFormField
                      name="default_model_name"
                      label="Default Model"
                      subtext="The model to use by default for this provider. Must be one of the models listed above."
                      placeholder="e.g. gpt-4"
                    />

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
              }}
            </Formik>
          </>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
