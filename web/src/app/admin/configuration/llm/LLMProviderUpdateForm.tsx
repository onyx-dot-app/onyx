"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
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
  FileUploadFormField,
} from "@/components/admin/connectors/Field";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { defaultModelsByProvider } from "@/lib/hooks";
import { LLMProviderView, WellKnownLLMProviderDescriptor } from "./interfaces";
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
  hideSuccess,
  firstTimeConfiguration = false,
  hasAdvancedOptions = false,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor;
  onClose: () => void;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
  hideSuccess?: boolean; // Set this when this is the first time the user is setting SmartSearch up.
  firstTimeConfiguration?: boolean;
  hasAdvancedOptions?: boolean;
}) {
  const { t } = useTranslation();
  const { mutate } = useSWRConfig();

  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // Define the initial values based on the provider's requirements
  const initialValues = {
    name:
      existingLlmProvider?.name || (firstTimeConfiguration ? "Default" : ""),
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
    api_key_changed: false,
  };

  // Setup validation schema if required
  const validationSchema = Yup.object({
    name: Yup.string().required(t(k.DISPLAY_NAME_REQUIRED)),
    api_key: llmProviderDescriptor.api_key_required
      ? Yup.string().required(t(k.API_KEY_REQUIRED))
      : Yup.string(),
    api_base: llmProviderDescriptor.api_base_required
      ? Yup.string().required(t(k.API_BASE_REQUIRED))
      : Yup.string(),
    api_version: llmProviderDescriptor.api_version_required
      ? Yup.string().required(t(k.API_VERSION_REQUIRED))
      : Yup.string(),
    ...(llmProviderDescriptor.custom_config_keys
      ? {
          custom_config: Yup.object(
            llmProviderDescriptor.custom_config_keys.reduce(
              (acc, customConfigKey) => {
                if (customConfigKey.is_required) {
                  acc[customConfigKey.name] = Yup.string().required(
                    `${
                      customConfigKey.display_name || customConfigKey.name
                    } ${t(k.FIELD_REQUIRED)}`
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
      ? Yup.string().required(t(k.DEPLOYMENT_NAME_REQUIRED))
      : Yup.string().nullable(),
    default_model_name: Yup.string().required(t(k.MODEL_NAME_REQUIRED)),
    fast_default_model_name: Yup.string().nullable(),
    // EE Only
    is_public: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    display_model_names: Yup.array().of(Yup.string()),
    api_key_changed: Yup.boolean(),
  });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        values.api_key_changed = values.api_key !== initialValues.api_key;

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
            ? `${t(k.FAILED_TO_UPDATE_PROVIDER)} ${errorMsg}`
            : `${t(k.FAILED_TO_ENABLE_PROVIDER)} ${errorMsg}`;
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
            const fullErrorMsg = `${t(
              k.FAILED_TO_SET_PROVIDER_AS_DEFA
            )} ${errorMsg}`;
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
          ? t(k.PROVIDER_UPDATED_SUCCESSFULLY)
          : t(k.PROVIDER_ENABLED_SUCCESSFULLY);

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
          {!firstTimeConfiguration && (
            <TextFormField
              name="name"
              label={t(k.DISPLAY_NAME_LABEL)}
              subtext={t(k.DISPLAY_NAME_SUBTEXT)}
              placeholder={t(k.DISPLAY_NAME_PLACEHOLDER)}
              disabled={existingLlmProvider ? true : false}
            />
          )}

          {llmProviderDescriptor.api_key_required && (
            <TextFormField
              small={firstTimeConfiguration}
              name="api_key"
              label="API Key"
              placeholder="API Key"
              type="password"
            />
          )}

          {llmProviderDescriptor.api_base_required && (
            <TextFormField
              small={firstTimeConfiguration}
              name="api_base"
              label="API Base"
              placeholder="API Base"
            />
          )}

          {llmProviderDescriptor.api_version_required && (
            <TextFormField
              small={firstTimeConfiguration}
              name="api_version"
              label="API Version"
              placeholder="API Version"
            />
          )}

          {llmProviderDescriptor.custom_config_keys?.map((customConfigKey) => {
            if (customConfigKey.key_type === "text_input") {
              return (
                <div key={customConfigKey.name}>
                  <TextFormField
                    small={firstTimeConfiguration}
                    name={`custom_config.${customConfigKey.name}`}
                    label={
                      customConfigKey.is_required
                        ? customConfigKey.display_name
                        : `${t(k.OPTIONAL1)} ${customConfigKey.display_name}`
                    }
                    subtext={customConfigKey.description || undefined}
                  />
                </div>
              );
            } else if (customConfigKey.key_type === "file_input") {
              return (
                <FileUploadFormField
                  key={customConfigKey.name}
                  name={`custom_config.${customConfigKey.name}`}
                  label={customConfigKey.display_name}
                  subtext={customConfigKey.description || undefined}
                />
              );
            } else {
              throw new Error("Unreachable; there should only exist 2 options");
            }
          })}

          {hasAdvancedOptions && !firstTimeConfiguration && (
            <>
              <Separator />

              {llmProviderDescriptor.llm_names.length > 0 ? (
                <SelectorFormField
                  name="default_model_name"
                  subtext={t(k.DEFAULT_MODEL_SUBTEXT)}
                  label={t(k.DEFAULT_MODEL_LABEL)}
                  options={llmProviderDescriptor.llm_names.map((name) => ({
                    // don't clean up names here to give admins descriptive names / handle duplicates
                    // like us.anthropic.claude-3-7-sonnet-20250219-v1:0 and anthropic.claude-3-7-sonnet-20250219-v1:0
                    name: name,
                    value: name,
                  }))}
                  maxHeight="max-h-56"
                />
              ) : (
                <TextFormField
                  name="default_model_name"
                  subtext={t(k.DEFAULT_MODEL_SUBTEXT)}
                  label={t(k.DEFAULT_MODEL_LABEL)}
                  placeholder={t(k.DEFAULT_MODEL_PLACEHOLDER)}
                />
              )}

              {llmProviderDescriptor.deployment_name_required && (
                <TextFormField
                  name="deployment_name"
                  label={t(k.DEPLOYMENT_NAME_LABEL)}
                  placeholder={t(k.DEPLOYMENT_NAME_PLACEHOLDER)}
                />
              )}

              {!llmProviderDescriptor.single_model_supported &&
                (llmProviderDescriptor.llm_names.length > 0 ? (
                  <SelectorFormField
                    name="fast_default_model_name"
                    subtext={`${t(k.THE_MODEL_TO_USE_FOR_LIGHTER_F1)}`}
                    label={t(k.FAST_MODEL_OPTIONAL_LABEL)}
                    options={llmProviderDescriptor.llm_names.map((name) => ({
                      // don't clean up names here to give admins descriptive names / handle duplicates
                      // like us.anthropic.claude-3-7-sonnet-20250219-v1:0 and anthropic.claude-3-7-sonnet-20250219-v1:0
                      name: name,
                      value: name,
                    }))}
                    includeDefault
                    maxHeight="max-h-56"
                  />
                ) : (
                  <TextFormField
                    name="fast_default_model_name"
                    subtext={`${t(k.THE_MODEL_TO_USE_FOR_LIGHTER_F1)}`}
                    label={t(k.FAST_MODEL_OPTIONAL_LABEL)}
                    placeholder={t(k.FAST_MODEL_EXAMPLE_PLACEHOLDER)}
                  />
                ))}

              {hasAdvancedOptions && (
                <>
                  <Separator />
                  <AdvancedOptionsToggle
                    showAdvancedOptions={showAdvancedOptions}
                    setShowAdvancedOptions={setShowAdvancedOptions}
                  />

                  {showAdvancedOptions && (
                    <>
                      {llmProviderDescriptor.llm_names.length > 0 && (
                        <div className="w-full">
                          <MultiSelectField
                            selectedInitially={
                              formikProps.values.display_model_names
                            }
                            name="display_model_names"
                            label={t(k.DISPLAY_MODELS_LABEL)}
                            subtext={t(k.DISPLAY_MODELS_SUBTEXT)}
                            options={llmProviderDescriptor.llm_names.map(
                              (name) => ({
                                value: name,
                                // don't clean up names here to give admins descriptive names / handle duplicates
                                // like us.anthropic.claude-3-7-sonnet-20250219-v1:0 and anthropic.claude-3-7-sonnet-20250219-v1:0
                                label: name,
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
            </>
          )}

          {/* NOTE: this is above the test button to make sure it's visible */}
          {testError && <Text className="text-error mt-2">{testError}</Text>}

          <div className="flex w-full mt-4">
            <Button type="submit" variant="submit">
              {isTesting ? (
                <LoadingAnimation text="Testing" />
              ) : existingLlmProvider ? (
                t(k.UPDATE)
              ) : (
                t(k.ENABLE)
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
                    alert(`${t(k.FAILED_TO_DELETE_PROVIDER)} ${errorMsg}`);
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
                {t(k.DELETE)}
              </Button>
            )}
          </div>
        </Form>
      )}
    </Formik>
  );
}
