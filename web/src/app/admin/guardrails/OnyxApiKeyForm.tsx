"use client";

import React from "react";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import { Form, Formik } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  TextFormField,
  SelectorFormField,
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
            // Store config in the textarea as a pretty JSON string
            config: apiKey?.config ? JSON.stringify(apiKey.config, null, 2) : "",
            template: "",
            validator_type: apiKey?.validator_type,
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // Prepare the payload with the UserRole
            let parsedConfig: any = undefined;
            try {
              parsedConfig = values.config ? JSON.parse(values.config as unknown as string) : undefined;
            } catch (e) {
              formikHelpers.setSubmitting(false);
              setPopup({
                message: "Invalid JSON in config",
                type: "error",
              });
              return;
            }

            const payload = {
              name: values.name,
              description: values.description,
              config: parsedConfig,
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
                  if (tpl && tpl.config !== undefined) {
                    try {
                      const pretty = JSON.stringify(tpl.config, null, 2);
                      setFieldValue("config", pretty);
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

              <TextFormField
                maxWidth="max-w-lg"
                name="config"
                label={t(k.VALIDATOR_SETTINGS_LABEL)}
                placeholder={t(k.VALIDATOR_SETTINGS_PLACEHOLDER)}
                className="[&_input]:placeholder:text-text-muted/50"
                isTextArea={true}
                isCode={true}
              />

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
