"use client";

import { Button, Text } from "@opal/components";
import { useTranslations } from "next-intl";
import { TextFormField, TypedFileUploadFormField } from "@/components/Field";
import { Form, Formik, FormikHelpers } from "formik";
import { toast } from "@opal/layouts";
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
import type { Credential } from "@/lib/credentials/types";
import {
  createEditingValidationSchema,
  createInitialValues,
  getCredentialFileType,
  getCredentialSpec,
  getEditableCredentialFields,
} from "@/lib/credentials/utils";
import { SvgCheckSquare, SvgTrash } from "@opal/icons";
import type {
  CredentialFieldValues,
  CredentialFormValues,
} from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/connectors/types/source";

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
  const t = useTranslations("admin");
  const fieldCopy = useCredentialFieldCopy(sourceType);
  const spec = getCredentialSpec(sourceType);

  // The spec says which fields are secret. A stored key it does not list
  // keeps the old guess from its name.
  function isSecretField(key: string): boolean {
    const field = spec?.fields[key];
    if (field) return field.kind === "secret";
    const lower = key.toLowerCase();
    return (
      lower.includes("token") ||
      lower.includes("password") ||
      lower.includes("secret")
    );
  }
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
      toast.error(t("credentials.edit.updateError.toast"));
    } finally {
      formikHelpers.setSubmitting(false);
    }
  };

  return (
    <div className="flex w-full flex-col gap-y-6">
      <Text as="p">{t("credentials.edit.permissions.note")}</Text>

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
              label={t("credentials.edit.name.label")}
            />

            {Object.entries(editableCredentialFields).map(([key, value]) =>
              getCredentialFileType(key) !== null ? (
                <TypedFileUploadFormField
                  key={key}
                  name={key}
                  label={fieldCopy(key).title}
                />
              ) : (
                <TextFormField
                  includeRevert
                  key={key}
                  name={key}
                  placeholder={value == null ? undefined : String(value)}
                  label={fieldCopy(key).title}
                  type={isSecretField(key) ? "password" : "text"}
                  disabled={key === "authentication_method"}
                />
              )
            )}
            <div className="flex justify-between w-full">
              <Button onClick={() => resetForm()} icon={SvgTrash}>
                {t("credentials.edit.resetButton.label")}
              </Button>
              <Button
                disabled={isSubmitting}
                type="submit"
                icon={SvgCheckSquare}
              >
                {t("credentials.edit.updateButton.label")}
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </div>
  );
}
