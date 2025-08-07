import React from "react";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";

import { FaNewspaper, FaTrash } from "react-icons/fa";
import { TextFormField, TypedFileUploadFormField } from "@/components/Field";
import { Form, Formik, FormikHelpers } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  Credential,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";
import { createEditingValidationSchema, createInitialValues } from "../lib";
import { dictionaryType, formType } from "../types";
import { isTypedFileField } from "@/lib/connectors/fileTypes";

const EditCredential = ({
  credential,
  onClose,
  setPopup,
  onUpdate,
}: {
  credential: Credential<dictionaryType>;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  onUpdate: (
    selectedCredentialId: Credential<any>,
    details: any,
    onSuccess: () => void
  ) => Promise<void>;
}) => {
  const validationSchema = createEditingValidationSchema(
    credential.credential_json
  );
  const initialValues = createInitialValues(credential);

  const handleSubmit = async (
    values: formType,
    formikHelpers: FormikHelpers<formType>
  ) => {
    formikHelpers.setSubmitting(true);
    try {
      await onUpdate(credential, values, onClose);
    } catch (error) {
      console.error("Error updating credential:", error);
      setPopup({ message: "Error updating credential", type: "error" });
    } finally {
      formikHelpers.setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-y-6">
      <Text>
        Ensure that you update to a credential with the proper permissions!
      </Text>

      <Formik
        initialValues={initialValues}
        validationSchema={validationSchema}
        onSubmit={handleSubmit}
      >
        {({ isSubmitting, resetForm }) => (
          <Form>
            <TextFormField
              includeRevert
              name="name"
              placeholder={credential.name || ""}
              label="Name (optional):"
            />

            {Object.entries(credential.credential_json).map(([key, value]) =>
              isTypedFileField(key) ? (
                <TypedFileUploadFormField
                  key={key}
                  name={key}
                  label={getDisplayNameForCredentialKey(key)}
                />
              ) : (
                <TextFormField
                  includeRevert
                  key={key}
                  name={key}
                  placeholder={value as string}
                  label={getDisplayNameForCredentialKey(key)}
                  type={
                    key.toLowerCase().includes("token") ||
                    key.toLowerCase().includes("password")
                      ? "password"
                      : "text"
                  }
                  disabled={key === "authentication_method"}
                />
              )
            )}
            <div className="flex justify-between w-full">
              <Button type="button" onClick={() => resetForm()}>
                <div className="flex gap-x-2 items-center w-full border-none">
                  <FaTrash />
                  <p>Reset Changes</p>
                </div>
              </Button>
              <Button
                type="submit"
                disabled={isSubmitting}
                className="bg-indigo-500 hover:bg-indigo-400"
              >
                <div className="flex gap-x-2 items-center w-full border-none">
                  <FaNewspaper />
                  <p>Update</p>
                </div>
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </div>
  );
};

export default EditCredential;
