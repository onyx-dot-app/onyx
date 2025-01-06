import { LoadingAnimation } from "@/components/Loading";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import Text from "@/components/ui/text";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { Form, Formik } from "formik";
import { FiTrash } from "react-icons/fi";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import {
  SelectorFormField,
  TextFormField,
  MultiSelectField,
} from "@/components/admin/connectors/Field";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { defaultModelsByProvider, getDisplayNameForModel } from "@/lib/hooks";
import { FullLLMProvider, WellKnownLLMProviderDescriptor } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";

export function LLMProviderUpdateForm({
  llmProviderDescriptor,
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
  hideAdvanced,
  hideSuccess,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor;
  onClose: () => void;
  existingLlmProvider?: FullLLMProvider;
  shouldMarkAsDefault?: boolean;
  hideAdvanced?: boolean;
  setPopup?: (popup: PopupSpec) => void;
  hideSuccess?: boolean;
}) {
  const { mutate } = useSWRConfig();

  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // Define the initial values based on the provider's requirements
  const initialValues = {
    name: existingLlmProvider?.name || (hideAdvanced ? "Default" : ""),
    api_key: existingLlmProvider?.api_key ?? "",
    api_base: existingLlmProvider?.api_base ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    default_model_name:
      existingLlmProvider?.default_model_name ??
      (llmProviderDescriptor.default_model ||
        llmProviderDescriptor.llm_names[0]),
    fast_default_model_name:
      existingLlmProvider?.fast_default_model_name ??
      (llmProviderDescriptor.default_fast_model || null),
    custom_config:
      existingLlmProvider?.custom_config ??
      llmProviderDescriptor.custom_config_keys?.reduce(
        (acc, customConfigKey) => {
          acc[customConfigKey.name] = "";
          return acc;
        },
        {} as { [key: string]: string }
      ),
    is_public: existingLlmProvider?.is_public ?? true,
    groups: existingLlmProvider?.groups ?? [],
    display_model_names:
      existingLlmProvider?.display_model_names ||
      defaultModelsByProvider[llmProviderDescriptor.name] ||
      [],
    deployment_name: existingLlmProvider?.deployment_name,
  };

  // Setup validation schema if required
  const validationSchema = Yup.object({
    name: Yup.string().required("Display Name is required"),
    api_key: llmProviderDescriptor.api_key_required
      ? Yup.string().required("API Key is required")
      : Yup.string(),
    api_base: llmProviderDescriptor.api_base_required
      ? Yup.string().required("API Base is required")
      : Yup.string(),
    api_version: llmProviderDescriptor.api_version_required
      ? Yup.string().required("API Version is required")
      : Yup.string(),
    ...(llmProviderDescriptor.custom_config_keys
      ? {
          custom_config: Yup.object(
            llmProviderDescriptor.custom_config_keys.reduce(
              (acc, customConfigKey) => {
                if (customConfigKey.is_required) {
                  acc[customConfigKey.name] = Yup.string().required(
                    `${customConfigKey.name} is required`
                  );
                }
                return acc;
              },
              {} as { [key: string]: Yup.StringSchema }
            )
          ),
        }
      : {}),
    deployment_name: llmProviderDescriptor.deployment_name_required
      ? Yup.string().required("Deployment Name is required")
      : Yup.string().nullable(),
    default_model_name: Yup.string().required("Model name is required"),
    fast_default_model_name: Yup.string().nullable(),
    // EE Only
    is_public: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    display_model_names: Yup.array().of(Yup.string()),
  });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        // test the configuration
        if (!isEqual(values, initialValues)) {
          setIsTesting(true);

          const response = await fetch("/api/admin/llm/test", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              provider: llmProviderDescriptor.name,
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
              provider: llmProviderDescriptor.name,
              ...values,
              fast_default_model_name:
                values.fast_default_model_name || values.default_model_name,
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
          const newLlmProvider = (await response.json()) as FullLLMProvider;
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
      {(formikProps) => (
        <Form className="gap-y-4 items-stretch mt-6">
          {!hideAdvanced && (
            <TextFormField
              name="name"
              label="Display Name"
              subtext="A name which you can use to identify this provider when selecting it in the UI."
              placeholder="Display Name"
              disabled={existingLlmProvider ? true : false}
            />
          )}

          {llmProviderDescriptor.api_key_required && (
            <TextFormField
              small={hideAdvanced}
              name="api_key"
              label="API Key"
              placeholder="API Key"
              type="password"
            />
          )}

          {llmProviderDescriptor.api_base_required && (
            <TextFormField
              small={hideAdvanced}
              name="api_base"
              label="API Base"
              placeholder="API Base"
            />
          )}

          {llmProviderDescriptor.api_version_required && (
            <TextFormField
              small={hideAdvanced}
              name="api_version"
              label="API Version"
              placeholder="API Version"
            />
          )}

          {llmProviderDescriptor.custom_config_keys?.map((customConfigKey) => (
            <div key={customConfigKey.name}>
              <TextFormField
                small={hideAdvanced}
                name={`custom_config.${customConfigKey.name}`}
                label={
                  customConfigKey.is_required
                    ? customConfigKey.name
                    : `[Optional] ${customConfigKey.name}`
                }
                subtext={customConfigKey.description || undefined}
              />
            </div>
          ))}

          {!(hideAdvanced && llmProviderDescriptor.name != "azure") && (
            <>
              <Separator />
              {llmProviderDescriptor.llm_names.length > 0 ? (
                <SelectorFormField
                  name="default_model_name"
                  subtext="The model to use by default for this provider unless otherwise specified."
                  label="Default Model"
                  options={llmProviderDescriptor.llm_names.map((name) => ({
                    name: getDisplayNameForModel(name),
                    value: name,
                  }))}
                  maxHeight="max-h-56"
                />
              ) : (
                <TextFormField
                  name="default_model_name"
                  subtext="The model to use by default for this provider unless otherwise specified."
                  label="Default Model"
                  placeholder="E.g. gpt-4"
                />
              )}
              {llmProviderDescriptor.deployment_name_required && (
                <TextFormField
                  small={hideAdvanced}
                  name="deployment_name"
                  label="Deployment Name"
                  placeholder="Deployment Name"
                />
              )}
              {!llmProviderDescriptor.single_model_supported &&
                (llmProviderDescriptor.llm_names.length > 0 ? (
                  <SelectorFormField
                    name="fast_default_model_name"
                    subtext={`The model to use for lighter flows like \`LLM Chunk Filter\` 
                for this provider. If \`Default\` is specified, will use 
                the Default Model configured above.`}
                    label="[Optional] Fast Model"
                    options={llmProviderDescriptor.llm_names.map((name) => ({
                      name: getDisplayNameForModel(name),
                      value: name,
                    }))}
                    includeDefault
                    maxHeight="max-h-56"
                  />
                ) : (
                  <TextFormField
                    name="fast_default_model_name"
                    subtext={`The model to use for lighter flows like \`LLM Chunk Filter\` 
                for this provider. If \`Default\` is specified, will use 
                the Default Model configured above.`}
                    label="[Optional] Fast Model"
                    placeholder="E.g. gpt-4"
                  />
                ))}

              {llmProviderDescriptor.name != "azure" && (
                <>
                  <Separator />

                  <AdvancedOptionsToggle
                    showAdvancedOptions={showAdvancedOptions}
                    setShowAdvancedOptions={setShowAdvancedOptions}
                  />
                </>
              )}
              {showAdvancedOptions && (
                <>
                  {llmProviderDescriptor.llm_names.length > 0 && (
                    <div className="w-full">
                      <MultiSelectField
                        selectedInitially={
                          formikProps.values.display_model_names
                        }
                        name="display_model_names"
                        label="Display Models"
                        subtext="Select the models to make available to users. Unselected models will not be available."
                        options={llmProviderDescriptor.llm_names.map(
                          (name) => ({
                            value: name,
                            label: getDisplayNameForModel(name),
                          })
                        )}
                        onChange={(selected) =>
                          formikProps.setFieldValue(
                            "display_model_names",
                            selected
                          )
                        }
                      />
                    </div>
                  )}

                  <IsPublicGroupSelector
                    formikProps={formikProps}
                    objectName="LLM Provider"
                    publicToWhom="all users"
                    enforceGroupSelection={true}
                  />
                </>
              )}
            </>
          )}
          <div>
            {/* NOTE: this is above the test button to make sure it's visible */}
            {testError && <Text className="text-error mt-2">{testError}</Text>}

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

                    // If the deleted provider was the default, set the first remaining provider as default
                    const remainingProvidersResponse = await fetch(
                      LLM_PROVIDERS_ADMIN_URL
                    );
                    if (remainingProvidersResponse.ok) {
                      const remainingProviders =
                        await remainingProvidersResponse.json();

                      if (remainingProviders.length > 0) {
                        const setDefaultResponse = await fetch(
                          `${LLM_PROVIDERS_ADMIN_URL}/${remainingProviders[0].id}/default`,
                          {
                            method: "POST",
                          }
                        );
                        if (!setDefaultResponse.ok) {
                          console.error("Failed to set new default provider");
                        }
                      }
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
      )}
    </Formik>
  );
}
