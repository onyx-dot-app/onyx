import { Button, Text } from "@opal/components";

import { TextFormField, TypedFileUploadFormField } from "@/components/Field";
import { Form, Formik, FormikHelpers } from "formik";
import { toast } from "@opal/layouts";
import {
  Credential,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";
import {
  createEditingValidationSchema,
  createInitialValues,
  getEditableCredentialFields,
} from "@/lib/credentials/utils";
import { isTypedFileField } from "@/lib/connectors/fileTypes";
import { SvgCheckSquare, SvgTrash } from "@opal/icons";
import type {
  CredentialFieldValues,
  CredentialFormValues,
} from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/types";

export interface EditCredentialProps {
  credential: Credential<CredentialFieldValues>;
  sourceType: ValidSources;
  onClose: () => void;
  onUpdate: (
    selectedCredentialId: Credential<any>,
    details: any,
    onSuccess: () => void
  ) => Promise<void>;
}

export default function EditCredential({
  credential,
  sourceType,
  onClose,
  onUpdate,
}: EditCredentialProps) {
  const editableCredentialFields = getEditableCredentialFields(
    credential,
    sourceType
  );
  const validationSchema = createEditingValidationSchema(
    editableCredentialFields
  );
  const initialValues = createInitialValues(
    credential,
    editableCredentialFields
  );

  const handleSubmit = async (
    values: CredentialFormValues,
    formikHelpers: FormikHelpers<CredentialFormValues>
  ) => {
    formikHelpers.setSubmitting(true);
    try {
      await onUpdate(credential, values, onClose);
    } catch (error) {
      console.error("Error updating credential:", error);
      toast.error("Error updating credential");
    } finally {
      formikHelpers.setSubmitting(false);
    }
  };

  return (
    <div className="flex w-full flex-col gap-y-6">
      <Text as="p">
        Ensure that you update to a credential with the proper permissions!
      </Text>

      <Formik
        initialValues={initialValues}
        validationSchema={validationSchema}
        onSubmit={handleSubmit}
      >
        {({ isSubmitting, resetForm }) => (
          <Form className="flex w-full flex-col gap-y-4">
            <TextFormField
              includeRevert
              name="name"
              placeholder={credential.name || ""}
              label="Name (optional):"
            />

            {Object.entries(editableCredentialFields).map(([key, value]) =>
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
                  placeholder={value == null ? undefined : String(value)}
                  label={getDisplayNameForCredentialKey(key)}
                  type={
                    key.toLowerCase().includes("token") ||
                    key.toLowerCase().includes("password") ||
                    key.toLowerCase().includes("secret")
                      ? "password"
                      : "text"
                  }
                  disabled={key === "authentication_method"}
                />
              )
            )}
            <div className="flex justify-between w-full">
              <Button onClick={() => resetForm()} icon={SvgTrash}>
                Reset Changes
              </Button>
              <Button
                disabled={isSubmitting}
                type="submit"
                icon={SvgCheckSquare}
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
