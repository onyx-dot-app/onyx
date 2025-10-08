"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import { Form, Formik } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  TextFormField,
} from "@/components/admin/connectors/Field";
import { createApiKey, updateApiKey } from "./lib";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { APIKey } from "./types";

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
            config: apiKey?.config
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // Prepare the payload with the UserRole
            const payload = {
              ...values,
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
