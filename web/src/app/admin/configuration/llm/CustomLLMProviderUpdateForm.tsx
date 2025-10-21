import { LoadingAnimation } from "@/components/Loading";
import Text from "@/components/ui/text";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import {
  ArrayHelpers,
  ErrorMessage,
  Field,
  FieldArray,
  Form,
  Formik,
} from "formik";
import { FiPlus, FiTrash, FiX } from "react-icons/fi";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import { Label, SubLabel, TextFormField } from "@/components/Field";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { LLMProviderView } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { ModelConfigurationField } from "./ModelConfigurationField";

function customConfigProcessing(customConfigsList: [string, string][]) {
  const customConfig: { [key: string]: string } = {};
  customConfigsList.forEach(([key, value]) => {
    customConfig[key] = value;
  });
  return customConfig;
}

export function CustomLLMProviderUpdateForm({
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
  hideSuccess,
}: {
  onClose: () => void;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
  hideSuccess?: boolean;
}) {
  const { mutate } = useSWRConfig();

  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // Define the initial values based on the provider's requirements
  const initialValues = {
    name: existingLlmProvider?.name ?? "",
    provider: existingLlmProvider?.provider ?? "",
    api_key: existingLlmProvider?.api_key ?? "",
    api_base: existingLlmProvider?.api_base ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    default_model_name: existingLlmProvider?.default_model_name ?? null,
    fast_default_model_name:
      existingLlmProvider?.fast_default_model_name ?? null,
    model_configurations: existingLlmProvider?.model_configurations.map(
      (modelConfiguration) => ({
        ...modelConfiguration,
        max_input_tokens: modelConfiguration.max_input_tokens ?? null,
      })
    ) ?? [{ name: "", is_visible: true, max_input_tokens: null }],
    custom_config_list: existingLlmProvider?.custom_config
      ? Object.entries(existingLlmProvider.custom_config)
      : [],
    is_public: existingLlmProvider?.is_public ?? true,
    groups: existingLlmProvider?.groups ?? [],
    deployment_name: existingLlmProvider?.deployment_name ?? null,
    api_key_changed: false,
  };

  // Setup validation schema if required
  const validationSchema = Yup.object({
    name: Yup.string().required("Display Name is required"),
    provider: Yup.string().required("Provider Name is required"),
    api_key: Yup.string(),
    api_base: Yup.string(),
    api_version: Yup.string(),
    model_configurations: Yup.array(
      Yup.object({
        name: Yup.string().required("Model name is required"),
        is_visible: Yup.boolean().required("Visibility is required"),
        // Coerce empty string from input field into null so it's optional
        max_input_tokens: Yup.number()
          .transform((value, originalValue) =>
            originalValue === "" || originalValue === undefined ? null : value
          )
          .nullable()
          .optional(),
      })
    ),
    default_model_name: Yup.string().required("Model name is required"),
    fast_default_model_name: Yup.string().nullable(),
    custom_config_list: Yup.array(),
    // EE Only
    is_public: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    deployment_name: Yup.string().nullable(),
  });

  const arePaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        // build final payload
        const finalValues = { ...values };
        finalValues.model_configurations = finalValues.model_configurations.map(
          (modelConfiguration) => ({
            ...modelConfiguration,
            max_input_tokens:
              modelConfiguration.max_input_tokens === null ||
              modelConfiguration.max_input_tokens === undefined
                ? null
                : modelConfiguration.max_input_tokens,
            supports_image_input: false, // doesn't matter, not used
          })
        );
        finalValues.api_key_changed = values.api_key !== initialValues.api_key;

        if (values.model_configurations.length === 0) {
          const fullErrorMsg = "At least one model name is required";
          if (setPopup) {
            setPopup({
              type: "error",
              message: fullErrorMsg,
            });
          } else {
            alert(fullErrorMsg);
          }
          setSubmitting(false);
          return;
        }

        // test the configuration
        if (!isEqual(values, initialValues)) {
          setIsTesting(true);

          const response = await fetch("/api/admin/llm/test", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              custom_config: customConfigProcessing(values.custom_config_list),
              ...values,
            }),
          });
          setIsTesting(false);

          if (!response.ok) {
            const errorMsg = (await response.json()).detail;
            setTestError(errorMsg);
            return;
          }
        }

        const response = await fetch(
          `${LLM_PROVIDERS_ADMIN_URL}${
            existingLlmProvider ? "" : "?is_creation=true"
          }`,
          {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              ...values,
              custom_config: customConfigProcessing(values.custom_config_list),
            }),
          }
        );

        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          const fullErrorMsg = existingLlmProvider
            ? `Failed to update provider: ${errorMsg}`
            : `Failed to enable provider: ${errorMsg}`;
          if (setPopup) {
            setPopup({
              type: "error",
              message: fullErrorMsg,
            });
          } else {
            alert(fullErrorMsg);
          }
          return;
        }

        if (shouldMarkAsDefault) {
          const newLlmProvider = (await response.json()) as LLMProviderView;
          const setDefaultResponse = await fetch(
            `${LLM_PROVIDERS_ADMIN_URL}/${newLlmProvider.id}/default`,
            {
              method: "POST",
            }
          );
          if (!setDefaultResponse.ok) {
            const errorMsg = (await setDefaultResponse.json()).detail;
            const fullErrorMsg = `Failed to set provider as default: ${errorMsg}`;
            if (setPopup) {
              setPopup({
                type: "error",
                message: fullErrorMsg,
              });
            } else {
              alert(fullErrorMsg);
            }
            return;
          }
        }

        mutate(LLM_PROVIDERS_ADMIN_URL);
        onClose();

        const successMsg = existingLlmProvider
          ? "Provider updated successfully!"
          : "Provider enabled successfully!";
        if (!hideSuccess && setPopup) {
          setPopup({
            type: "success",
            message: successMsg,
          });
        } else {
          alert(successMsg);
        }

        setSubmitting(false);
      }}
    >
      {(formikProps) => {
        return (
          <Form className="gap-y-6 mt-8">
            <TextFormField
              name="name"
              label="Display Name"
              subtext="A name which you can use to identify this provider when selecting it in the UI."
              placeholder="Display Name"
              disabled={existingLlmProvider ? true : false}
            />

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

            <SubLabel>
              Fill in the following as is needed. Refer to the LiteLLM
              documentation for the model provider name specified above in order
              to determine which fields are required.
            </SubLabel>

            <TextFormField
              name="api_key"
              label="[Optional] API Key"
              placeholder="API Key"
              type="password"
            />

            {existingLlmProvider?.deployment_name && (
              <TextFormField
                name="deployment_name"
                label="[Optional] Deployment Name"
                placeholder="Deployment Name"
              />
            )}

            <TextFormField
              name="api_base"
              label="[Optional] API Base"
              placeholder="API Base"
            />

            <TextFormField
              name="api_version"
              label="[Optional] API Version"
              placeholder="API Version"
            />

            <Label>[Optional] Custom Configs</Label>
            <SubLabel>
              <>
                <div>
                  Additional configurations needed by the model provider. These
                  are passed to litellm via environment + as arguments into the
                  `completion` call.
                </div>

                <div className="mt-2">
                  For example, when configuring the Cloudflare provider, you
                  would need to set `CLOUDFLARE_ACCOUNT_ID` as the key and your
                  Cloudflare account ID as the value.
                </div>
              </>
            </SubLabel>

            <FieldArray
              name="custom_config_list"
              render={(arrayHelpers: ArrayHelpers<any[]>) => (
                <div className="w-full">
                  {formikProps.values.custom_config_list.map((_, index) => {
                    return (
                      <div
                        key={index}
                        className={(index === 0 ? "mt-2" : "mt-6") + " w-full"}
                      >
                        <div className="flex w-full">
                          <div className="w-full mr-6 border border-border p-3 rounded">
                            <div>
                              <Label>Key</Label>
                              <Field
                                name={`custom_config_list[${index}][0]`}
                                className={`
                                  border
                                  border-border
                                  bg-background
                                  rounded
                                  w-full
                                  py-2
                                  px-3
                                  mr-4
                                `}
                                autoComplete="off"
                              />
                              <ErrorMessage
                                name={`custom_config_list[${index}][0]`}
                                component="div"
                                className="text-error text-sm mt-1"
                              />
                            </div>

                            <div className="mt-3">
                              <Label>Value</Label>
                              <Field
                                name={`custom_config_list[${index}][1]`}
                                className={`
                                  border
                                  border-border
                                  bg-background
                                  rounded
                                  w-full
                                  py-2
                                  px-3
                                  mr-4
                                `}
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
                            <FiX
                              className="my-auto w-10 h-10 cursor-pointer hover:bg-accent-background-hovered rounded p-2"
                              onClick={() => arrayHelpers.remove(index)}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  })}

                  <Button
                    onClick={() => {
                      arrayHelpers.push(["", ""]);
                    }}
                    className="mt-3"
                    variant="next"
                    type="button"
                    icon={FiPlus}
                  >
                    Add New
                  </Button>
                </div>
              )}
            />

            <Separator />
            {!existingLlmProvider?.deployment_name && (
              <ModelConfigurationField
                name="model_configurations"
                formikProps={formikProps as any}
              />
            )}

            <Separator />
            <TextFormField
              name="default_model_name"
              subtext={`
              The model to use by default for this provider unless
              otherwise specified. Must be one of the models listed
              above.`}
              label="Default Model"
              placeholder="E.g. gpt-4"
            />

            {!existingLlmProvider?.deployment_name && (
              <TextFormField
                name="fast_default_model_name"
                subtext="The model to use for lighter flows like `LLM Chunk Filter` for this provider. If not set, will use the Default Model configured above."
                label="[Optional] Fast Model"
                placeholder="E.g. gpt-4"
              />
            )}

            {arePaidEnterpriseFeaturesEnabled && (
              <>
                <Separator />
                <AdvancedOptionsToggle
                  showAdvancedOptions={showAdvancedOptions}
                  setShowAdvancedOptions={setShowAdvancedOptions}
                />

                {showAdvancedOptions && (
                  <IsPublicGroupSelector
                    formikProps={formikProps}
                    objectName="LLM Provider"
                    publicToWhom="all users"
                    enforceGroupSelection={true}
                  />
                )}
              </>
            )}

            <div>
              {/* NOTE: this is above the test button to make sure it's visible */}
              {testError && (
                <Text className="text-error mt-2">{testError}</Text>
              )}

              <div className="flex w-full mt-4">
                <Button type="submit" variant="submit">
                  {isTesting ? (
                    <LoadingAnimation text="Testing" />
                  ) : existingLlmProvider ? (
                    "Update"
                  ) : (
                    "Enable"
                  )}
                </Button>
                {existingLlmProvider && (
                  <Button
                    type="button"
                    variant="destructive"
                    className="ml-3"
                    icon={FiTrash}
                    onClick={async () => {
                      const response = await fetch(
                        `${LLM_PROVIDERS_ADMIN_URL}/${existingLlmProvider.id}`,
                        {
                          method: "DELETE",
                        }
                      );
                      if (!response.ok) {
                        const errorMsg = (await response.json()).detail;
                        alert(`Failed to delete provider: ${errorMsg}`);
                        return;
                      }

                      mutate(LLM_PROVIDERS_ADMIN_URL);
                      onClose();
                    }}
                  >
                    Delete
                  </Button>
                )}
              </div>
            </div>
          </Form>
        );
      }}
    </Formik>
  );
}
