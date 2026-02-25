import { Form, Formik } from "formik";
import { toast } from "@/hooks/useToast";
import { createApiKey, updateApiKey } from "./lib";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { APIKey } from "./types";
import { SvgKey } from "@opal/icons";

export interface OnyxApiKeyFormProps {
  onClose: () => void;
  onCreateApiKey: (apiKey: APIKey) => void;
  apiKey?: APIKey;
}

export default function OnyxApiKeyForm({
  onClose,
  onCreateApiKey,
  apiKey,
}: OnyxApiKeyFormProps) {
  const isUpdate = apiKey !== undefined;

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm" height="lg">
        <Modal.Header
          icon={SvgKey}
          title={isUpdate ? "Update API Key" : "Create a new API Key"}
          onClose={onClose}
        />
        <Formik
          initialValues={{
            name: apiKey?.api_key_name || "",
            role: apiKey?.api_key_role || UserRole.BASIC.toString(),
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // Prepare the payload with the UserRole
            const payload = {
              ...values,
              role: values.role as UserRole, // Assign the role directly as a UserRole type
            };

            let response;
            if (isUpdate) {
              response = await updateApiKey(apiKey.api_key_id, payload);
            } else {
              response = await createApiKey(payload);
            }
            formikHelpers.setSubmitting(false);
            if (response.ok) {
              toast.success(
                isUpdate
                  ? "Successfully updated API key!"
                  : "Successfully created API key!"
              );
              if (!isUpdate) {
                onCreateApiKey(await response.json());
              }
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              toast.error(
                isUpdate
                  ? `Error updating API key - ${errorMsg}`
                  : `Error creating API key - ${errorMsg}`
              );
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form className="w-full overflow-visible">
              <Modal.Body>
                <Text as="p">
                  Choose a memorable name for your API key. This is optional and
                  can be added or changed later!
                </Text>

                <FormikField<string>
                  name="name"
                  render={(field, helper, _meta, state) => (
                    <FormField name="name" state={state} className="w-full">
                      <FormField.Label>Name (optional):</FormField.Label>
                      <FormField.Control>
                        <InputTypeIn
                          {...field}
                          placeholder=""
                          onClear={() => helper.setValue("")}
                          showClearButton={false}
                        />
                      </FormField.Control>
                    </FormField>
                  )}
                />

                <FormikField<string>
                  name="role"
                  render={(field, helper, _meta, state) => (
                    <FormField name="role" state={state} className="w-full">
                      <FormField.Label>Role:</FormField.Label>
                      <FormField.Control>
                        <InputComboBox
                          value={field.value}
                          onValueChange={(value) => helper.setValue(value)}
                          options={[
                            {
                              label: USER_ROLE_LABELS[UserRole.LIMITED],
                              value: UserRole.LIMITED.toString(),
                            },
                            {
                              label: USER_ROLE_LABELS[UserRole.BASIC],
                              value: UserRole.BASIC.toString(),
                            },
                            {
                              label: USER_ROLE_LABELS[UserRole.ADMIN],
                              value: UserRole.ADMIN.toString(),
                            },
                          ]}
                          placeholder="Select a role"
                          strict
                        />
                      </FormField.Control>
                      <FormField.Description>
                        Select the role for this API key. Limited has access to
                        simple public APIs. Basic has access to regular user
                        APIs. Admin has access to admin level APIs.
                      </FormField.Description>
                    </FormField>
                  )}
                />
              </Modal.Body>

              <Modal.Footer>
                <Button type="submit" disabled={isSubmitting}>
                  {isUpdate ? "Update" : "Create"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
