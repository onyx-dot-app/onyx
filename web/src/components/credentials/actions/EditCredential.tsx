import Button from "@/refresh-components/buttons/Button";
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
import { SvgTrash } from "@opal/icons";
export interface EditCredentialProps {
  credential: Credential<dictionaryType>;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  onUpdate: (
    selectedCredentialId: Credential<any>,
    details: any,
    onSuccess: () => void
  ) => Promise<void>;
}

export default function EditCredential({
  credential,
  onClose,
  setPopup,
  onUpdate,
}: EditCredentialProps) {
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
              <Button onClick={() => resetForm()} leftIcon={SvgTrash}>
                Reset Changes
              </Button>
              <Button
                type="submit"
                disabled={isSubmitting}
                className="bg-indigo-500 hover:bg-indigo-400"
                leftIcon={FaNewspaper}
              >
                Update
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </div>
  );
}
