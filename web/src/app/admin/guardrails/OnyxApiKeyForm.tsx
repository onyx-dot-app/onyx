"use client";

import React from "react";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import { Form, Formik } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  TextFormField,
  SelectorFormField,
  MultiSelectField,
  BooleanFormField,
} from "@/components/admin/connectors/Field";
import { createApiKey, updateApiKey } from "./lib";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import { APIKey } from "./types";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import MultiSelectDropdown from "@/components/MultiSelectDropdown";
import { LLMProviderView } from "@/app/admin/configuration/llm/interfaces";
import { getProviderIcon } from "@/app/admin/configuration/llm/interfaces";

interface OnyxApiKeyFormProps {
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  apiKey?: APIKey;
}

export const OnyxApiKeyForm = ({
  onClose,
  setPopup,
  apiKey,
}: OnyxApiKeyFormProps) => {
  const { t } = useTranslation();
  const { data: templates } = useSWR<any[]>(
    "/api/validators/templates",
    errorHandlingFetcher
  );

  const { data: llmProviders } = useSWR<LLMProviderView[]>(
    "/api/admin/llm/provider",
    errorHandlingFetcher
  );

  const isUpdate = apiKey !== undefined;

  const initialTemplateId = React.useMemo(() => {
    if (!isUpdate) return "";
    if (!Array.isArray(templates) || templates.length === 0) return "";
    try {
      const candidate = templates.find(
        (t) => String(t?.validator_type) === String(apiKey?.validator_type)
      );
      return candidate ? String(candidate.id) : "";
    } catch (_) {
      return "";
    }
  }, [isUpdate, templates, apiKey]);

  return (
    <Modal onOutsideClick={onClose} width="w-2/6">
      <>
        <h2 className="text-xl font-bold flex">
          {isUpdate ? t(k.UPDATE_VALIDATOR) : t(k.CREATE_NEW_VALIDATOR)}
        </h2>

        <Separator />

        <Formik
          enableReinitialize
          initialValues={{
            name: apiKey?.name,
            description: apiKey?.description,
            // Dynamic config values are flattened into form values by field name
            ...(apiKey?.config || {}),
            template: initialTemplateId,
            validator_type: apiKey?.validator_type,
            llm_provider_id:
              apiKey?.llm_provider_id ?? apiKey?.llm_provider?.id ?? "",
            // Preserve include_llm from top-level field if present
            include_llm: apiKey?.include_llm,
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // Build config object from dynamic fields based on selected template schema
            let configObject: Record<string, any> | undefined = undefined;
            try {
              const selectedTemplate = Array.isArray(templates)
                ? templates.find(
                    (t) =>
                      String(t?.id) === (values.template as unknown as string)
                  )
                : undefined;
              const schema: any[] | undefined = selectedTemplate?.config;
              if (Array.isArray(schema)) {
                configObject = schema.reduce(
                  (acc: Record<string, any>, field: any) => {
                    acc[field.name] = (values as any)[field.name];
                    return acc;
                  },
                  {}
                );
              } else {
                // If no template selected, try to infer config keys from values present in apiKey.config
                if (apiKey?.config) {
                  configObject = Object.keys(apiKey.config).reduce(
                    (acc: Record<string, any>, key: string) => {
                      acc[key] = (values as any)[key];
                      return acc;
                    },
                    {}
                  );
                }
              }
            } catch (_) {
              // noop, leave configObject undefined
            }

            const payload = {
              name: values.name,
              description: values.description,
              config: configObject,
              validator_type: values.validator_type,
              llm_provider_id: values.llm_provider_id
                ? Number(values.llm_provider_id)
                : undefined,
              // Ensure include_llm is explicitly boolean to avoid clearing on update
              include_llm: Boolean(
                (values as any).include_llm ?? apiKey?.include_llm ?? false
              ),
            };

            let response;
            if (isUpdate) {
              response = await updateApiKey(apiKey.id, payload);
            } else {
              response = await createApiKey(payload);
            }
            formikHelpers.setSubmitting(false);
            if (response.ok) {
              setPopup({
                message: isUpdate
                  ? t(k.VALIDATOR_UPDATED_SUCCESS)
                  : t(k.VALIDATOR_CREATED_SUCCESS),

                type: "success",
              });
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: `${
                  isUpdate
                    ? t(k.VALIDATOR_UPDATE_ERROR)
                    : t(k.VALIDATOR_CREATE_ERROR)
                }: ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form className="w-full overflow-auto p-2">
              <SelectorFormField
                name="template"
                label={t(k.VALIDATOR_TEMPLATE_LABEL)}
                options={
                  Array.isArray(templates)
                    ? templates.map((tpl, idx) => ({
                        value: String(tpl?.id),
                        name: tpl?.name || tpl?.id || `Шаблон ${idx + 1}`,
                      }))
                    : []
                }
                defaultValue=""
                disabled={!Array.isArray(templates) || templates.length === 0}
                onSelect={(selected) => {
                  const selectedId = selected as string;
                  setFieldValue("template", selectedId);
                  const tpl = Array.isArray(templates)
                    ? templates.find((t) => String(t?.id) === selectedId)
                    : undefined;

                  // Reset LLM provider selection when template changes
                  setFieldValue("llm_provider_id", "");

                  // Initialize dynamic fields from template schema and set validator_type
                  if (tpl && Array.isArray(tpl.config)) {
                    try {
                      // Keep include_llm in form state for later pass-through to backend
                      setFieldValue("include_llm", (tpl as any)?.include_llm);
                      tpl.config.forEach((field: any) => {
                        switch (field.type) {
                          case "multiselect":
                            setFieldValue(
                              field.name,
                              (values as any)[field.name] || []
                            );
                            break;
                          case "tags":
                            setFieldValue(
                              field.name,
                              (values as any)[field.name] || []
                            );
                            break;
                          case "checkbox":
                            setFieldValue(
                              field.name,
                              (values as any)[field.name] ?? false
                            );
                            break;
                          default:
                            setFieldValue(
                              field.name,
                              (values as any)[field.name] ?? ""
                            );
                        }
                      });
                      setFieldValue("validator_type", tpl.validator_type);
                    } catch (_) {
                      // noop
                    }
                  }
                }}
              />
              {(() => {
                const tpl = Array.isArray(templates)
                  ? templates.find((t) => String(t?.id) === values.template)
                  : undefined;
                return tpl ? <Text>{tpl?.description}</Text> : null;
              })()}

              <TextFormField
                name="name"
                label={t(k.VALIDATOR_NAME_LABEL)}
                autoCompleteDisabled={true}
              />

              {/* LLM Provider Selection */}
              {(() => {
                const selectedTemplate = Array.isArray(templates)
                  ? templates.find(
                      (t) =>
                        String(t?.id) === (values.template as unknown as string)
                    )
                  : undefined;

                // Check if the template includes LLM support
                const includeLlmRaw =
                  (values as any)?.include_llm ?? selectedTemplate?.include_llm;

                console.log("llmProviders", llmProviders);

                if (!includeLlmRaw) {
                  return null;
                }

                const llmOptions = llmProviders?.map((provider) => ({
                  value: String(provider.id),
                  name: provider.name,
                }));

                const selectedProvider = llmProviders?.find(
                  (p) => String(p.id) === String(values.llm_provider_id)
                );

                return (
                  <div className="flex flex-col gap-2">
                    <label className="text-sm font-medium text-text-700">
                      LLM Provider
                    </label>
                    <SelectorFormField
                      name="llm_provider_id"
                      label=""
                      options={llmOptions || []}
                      defaultValue=""
                      onSelect={(selected) => {
                        setFieldValue("llm_provider_id", selected);
                      }}
                    />
                    {selectedProvider && (
                      <div className="flex items-center gap-2 p-2 bg-gray-50 rounded-md">
                        {getProviderIcon(
                          selectedProvider.provider,
                          selectedProvider.default_model_name
                        )({ size: 16 })}
                        <span className="text-sm text-gray-600">
                          {selectedProvider.name} -{" "}
                          {selectedProvider.default_model_name}
                        </span>
                      </div>
                    )}

                    {/* Show connected LLM provider info if editing existing validator */}
                    {isUpdate && apiKey?.llm_provider && !selectedProvider && (
                      <div className="flex items-center gap-2 p-2 bg-blue-50 rounded-md">
                        {getProviderIcon(
                          apiKey.llm_provider.provider,
                          apiKey.llm_provider.default_model_name
                        )({ size: 16 })}
                        <span className="text-sm text-blue-600">
                          Connected: {apiKey.llm_provider.name} -{" "}
                          {apiKey.llm_provider.default_model_name}
                        </span>
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Dynamic fields rendered from selected template schema */}
              {(() => {
                const selectedTemplate = Array.isArray(templates)
                  ? templates.find(
                      (t) =>
                        String(t?.id) === (values.template as unknown as string)
                    )
                  : undefined;
                const schema: any[] | undefined = selectedTemplate?.config;
                if (!Array.isArray(schema)) {
                  return null;
                }

                return (
                  <div className="flex flex-col gap-4 mt-2 max-w-lg">
                    {schema.map((field) => {
                      if (!field || !field.type || !field.name) return null;
                      switch (field.type) {
                        case "select": {
                          const options = (field.values || []).map(
                            (v: string) => ({ value: v, name: v })
                          );
                          return (
                            <SelectorFormField
                              key={field.name}
                              name={field.name}
                              label={field.label}
                              options={options}
                              onSelect={(selected) =>
                                setFieldValue(field.name, selected)
                              }
                            />
                          );
                        }
                        case "multiselect": {
                          const options = (field.values || []).map(
                            (v: string) => ({
                              value: v,
                              label: t(v) || v,
                            })
                          );
                          return (
                            <MultiSelectField
                              key={field.name}
                              name={field.name}
                              label={field.label}
                              options={options}
                              selectedInitially={
                                (values as any)[field.name] || []
                              }
                              onChange={(selected) =>
                                setFieldValue(field.name, selected)
                              }
                            />
                          );
                        }
                        case "tags": {
                          const options = (field.values || []).map(
                            (v: string) => ({ value: v, label: v })
                          );
                          const selected = Array.isArray(
                            (values as any)[field.name]
                          )
                            ? ((values as any)[field.name] as string[]).map(
                                (s) => ({ value: s, label: s })
                              )
                            : [];
                          return (
                            <MultiSelectDropdown
                              key={field.name}
                              name={field.name}
                              label={field.label}
                              options={options}
                              creatable={true}
                              initialSelectedOptions={selected}
                              onChange={(selectedOptions) =>
                                setFieldValue(
                                  field.name,
                                  selectedOptions.map((opt) => opt.value)
                                )
                              }
                            />
                          );
                        }
                        case "text": {
                          return (
                            <TextFormField
                              key={field.name}
                              name={field.name}
                              label={field.label}
                              autoCompleteDisabled={true}
                            />
                          );
                        }
                        case "range": {
                          return (
                            <TextFormField
                              key={field.name}
                              name={field.name}
                              label={field.label}
                              type="number"
                              min={field.minValue}
                              autoCompleteDisabled={true}
                            />
                          );
                        }
                        case "checkbox": {
                          return (
                            <BooleanFormField
                              key={field.name}
                              name={field.name}
                              label={field.label}
                            />
                          );
                        }
                        default:
                          return null;
                      }
                    })}
                  </div>
                );
              })()}
              <div>
                <Button
                  type="submit"
                  size="sm"
                  variant="submit"
                  disabled={isSubmitting}
                >
                  {isUpdate ? t(k.UPDATE_BUTTON) : t(k.CREATE_BUTTON)}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </>
    </Modal>
  );
};
