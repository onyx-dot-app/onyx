"use client";

import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import { TypedFileUploadFormField } from "@/components/Field";
import { Form, Formik, FormikHelpers } from "formik";
import { toast } from "@/hooks/useToast";
import {
  Credential,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";
import {
  createEditingValidationSchema,
  createInitialValues,
} from "@/components/credentials/lib";
import { dictionaryType, formType } from "@/components/credentials/types";
import { isTypedFileField } from "@/lib/connectors/fileTypes";
import { SvgCheck, SvgTrash } from "@opal/icons";
import { Button } from "@opal/components";
import * as InputLayouts from "@/layouts/input-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

export interface EditCredentialProps {
  credential: Credential<dictionaryType>;
  onClose: () => void;
  onUpdate: (
    selectedCredentialId: Credential<any>,
    details: any,
    onSuccess: () => void
  ) => Promise<void>;
}

export default function EditCredential({
  credential,
  onClose,
  onUpdate,
}: EditCredentialProps) {
  const validationSchema = createEditingValidationSchema(
    credential.credential_json
  );
  const initialValues = createInitialValues(credential);

  async function handleSubmit(
    values: formType,
    formikHelpers: FormikHelpers<formType>
  ) {
    formikHelpers.setSubmitting(true);
    try {
      await onUpdate(credential, values, onClose);
    } catch (error) {
      console.error("Error updating credential:", error);
      toast.error("Error updating credential");
    } finally {
      formikHelpers.setSubmitting(false);
    }
  }

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={handleSubmit}
    >
      {({ isSubmitting, resetForm }) => (
        <Form>
          <Modal.Body>
            <GeneralLayouts.Section>
              <InputLayouts.Vertical name="name" title="Name" optional>
                <InputTypeInField
                  name="name"
                  placeholder={initialValues.name}
                />
              </InputLayouts.Vertical>

              {Object.entries(credential.credential_json).map(
                ([key, value]) => {
                  if (isTypedFileField(key))
                    return (
                      <TypedFileUploadFormField
                        key={key}
                        name={key}
                        label={getDisplayNameForCredentialKey(key)}
                      />
                    );

                  const inputType =
                    key.toLowerCase().includes("token") ||
                    key.toLowerCase().includes("password")
                      ? "password"
                      : "text";

                  return (
                    <InputLayouts.Vertical
                      key={key}
                      name={key}
                      title={getDisplayNameForCredentialKey(key)}
                    >
                      <InputTypeInField
                        name={key}
                        placeholder={
                          // # Note (@raunakab):
                          // Will always be a string since the `if (isTypedFileField)` check above will filter out `TypeFile` values.
                          value as string
                        }
                        type={inputType}
                        variant={
                          key === "authentication_method"
                            ? "disabled"
                            : undefined
                        }
                      />
                    </InputLayouts.Vertical>
                  );
                }
              )}
            </GeneralLayouts.Section>
          </Modal.Body>
          <Modal.Footer>
            <BasicModalFooter
              cancel={
                <Button
                  onClick={() => resetForm()}
                  icon={SvgTrash}
                  prominence="secondary"
                >
                  Reset Changes
                </Button>
              }
              submit={
                <Button type="submit" disabled={isSubmitting} icon={SvgCheck}>
                  Update
                </Button>
              }
            />
          </Modal.Footer>
        </Form>
      )}
    </Formik>
  );
}
