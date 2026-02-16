import { Form, Formik } from "formik";
import { toast } from "@/hooks/useToast";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { createApiKey, updateApiKey } from "./lib";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
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
        <Modal.Body>
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
                <Text as="p">
                  Choose a memorable name for your API key. This is optional and
                  can be added or changed later!
                </Text>

                <TextFormField name="name" label="Name (optional):" />

                <SelectorFormField
                  // defaultValue is managed by Formik
                  label="Role:"
                  subtext="Select the role for this API key.
                           Limited has access to simple public API's.
                           Basic has access to regular user API's.
                           Admin has access to admin level APIs."
                  name="role"
                  options={[
                    {
                      name: USER_ROLE_LABELS[UserRole.LIMITED],
                      value: UserRole.LIMITED.toString(),
                    },
                    {
                      name: USER_ROLE_LABELS[UserRole.BASIC],
                      value: UserRole.BASIC.toString(),
                    },
                    {
                      name: USER_ROLE_LABELS[UserRole.ADMIN],
                      value: UserRole.ADMIN.toString(),
                    },
                  ]}
                />

                <Button type="submit" disabled={isSubmitting}>
                  {isUpdate ? "Update" : "Create"}
                </Button>
              </Form>
            )}
          </Formik>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
