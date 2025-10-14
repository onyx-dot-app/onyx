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
import { APIKey } from "./types";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

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

  const isUpdate = apiKey !== undefined;

  return (
    <Modal onOutsideClick={onClose} width="w-2/6">
      <>
        <h2 className="text-xl font-bold flex">
          {isUpdate ? t(k.UPDATE_VALIDATOR) : t(k.CREATE_NEW_VALIDATOR)}
        </h2>

        <Separator />

        <Formik
          initialValues={{  
            name: apiKey?.name,
            description: apiKey?.description,
            // Dynamic config values are flattened into form values by field name
            ...(apiKey?.config || {}),
            template: "",
            validator_type: apiKey?.validator_type,
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // Build config object from dynamic fields based on selected template schema
            let configObject: Record<string, any> | undefined = undefined;
            try {
              const selectedTemplate = Array.isArray(templates)
                ? templates.find((t) => String(t?.id) === (values.template as unknown as string))
                : undefined;
              const schema: any[] | undefined = selectedTemplate?.config;
              if (Array.isArray(schema)) {
                configObject = schema.reduce((acc: Record<string, any>, field: any) => {
                  acc[field.name] = (values as any)[field.name];
                  return acc;
                }, {});
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
              validator_type: values.validator_type
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
                message: `${isUpdate ? t(k.VALIDATOR_UPDATE_ERROR) : t(k.VALIDATOR_CREATE_ERROR)}: ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form className="w-full overflow-visible">

              <SelectorFormField
                name="template"
                label={t(k.VALIDATOR_TEMPLATE_LABEL)}
                options={Array.isArray(templates)
                  ? templates.map((tpl, idx) => ({
                      value: String(tpl?.id),
                      name: tpl?.name || tpl?.id || `Шаблон ${idx + 1}`,
                    }))
                  : []}
                defaultValue=""
                disabled={!Array.isArray(templates) || templates.length === 0}
                onSelect={(selected) => {
                  const selectedId = selected as string;
                  const tpl = Array.isArray(templates)
                    ? templates.find((t) => String(t?.id) === selectedId)
                    : undefined;
                  // Initialize dynamic fields from template schema and set validator_type
                  if (tpl && Array.isArray(tpl.config)) {
                    try {
                      tpl.config.forEach((field: any) => {
                        switch (field.type) {
                          case "multiselect":
                            setFieldValue(field.name, (values as any)[field.name] || []);
                            break;
                          case "checkbox":
                            setFieldValue(field.name, (values as any)[field.name] ?? false);
                            break;
                          default:
                            setFieldValue(field.name, (values as any)[field.name] ?? "");
                        }
                      });
                      setFieldValue("validator_type", tpl.validator_type);
                    } catch (_) {
                      // noop
                    }
                  }
                }}
              />

              <TextFormField
                name="name"
                label={t(k.VALIDATOR_NAME_LABEL)}
                autoCompleteDisabled={true}
              />

              <TextFormField
                maxWidth="max-w-lg"
                name="description"
                label={t(k.VALIDATOR_DESCRIPTION_LABEL)}
                placeholder={t(k.VALIDATOR_DESCRIPTION_PLACEHOLDER)}
                className="[&_input]:placeholder:text-text-muted/50"
              />

              {/* Dynamic fields rendered from selected template schema */}
              {(() => {
                const selectedTemplate = Array.isArray(templates)
                  ? templates.find((t) => String(t?.id) === (values.template as unknown as string))
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
                          const options = (field.values || []).map((v: string) => ({ value: v, name: v }));
                          return (
                            <SelectorFormField
                              key={field.name}
                              name={field.name}
                              label={field.label}
                              options={options}
                              onSelect={(selected) => setFieldValue(field.name, selected)}
                            />
                          );
                        }
                        case "multiselect": {
                          const options = (field.values || []).map((v: string) => ({ value: v, label: v }));
                          return (
                            <MultiSelectField
                              key={field.name}
                              name={field.name}
                              label={field.label}
                              options={options}
                              selectedInitially={(values as any)[field.name] || []}
                              onChange={(selected) => setFieldValue(field.name, selected)}
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

              <Button
                type="submit"
                size="sm"
                variant="submit"
                disabled={isSubmitting}
              >
                {isUpdate ? t(k.UPDATE_BUTTON) : t(k.CREATE_BUTTON)}
              </Button>
            </Form>
          )}
        </Formik>
      </>
    </Modal>
  );
};
