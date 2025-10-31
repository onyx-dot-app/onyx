import { Form, Formik } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { createApiKey, updateApiKey } from "./lib";
import { Modal } from "@/components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { APIKey } from "./types";

// Sentinel value to represent "mirror my permissions" in the form
const MIRROR_ROLE_VALUE = "mirror" as const;

interface OnyxApiKeyFormProps {
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  onCreateApiKey: (apiKey: APIKey) => void;
  apiKey?: APIKey;
}

export const OnyxApiKeyForm = ({
  onClose,
  setPopup,
  onCreateApiKey,
  apiKey,
}: OnyxApiKeyFormProps) => {
  const isUpdate = apiKey !== undefined;

  return (
    <Modal onOutsideClick={onClose} width="w-2/6">
      <>
        <h2 className="text-xl font-bold flex">
          {isUpdate ? "Update API Key" : "Create a new API Key"}
        </h2>

        <Separator />

        <Formik
          initialValues={{
            name: apiKey?.api_key_name || "",
            role: apiKey?.api_key_role || MIRROR_ROLE_VALUE,
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // Convert mirror sentinel to null for the API
            const payload = {
              ...values,
              role:
                values.role === MIRROR_ROLE_VALUE
                  ? null
                  : (values.role as UserRole),
            };

            let response;
            if (isUpdate) {
              response = await updateApiKey(apiKey.api_key_id, payload);
            } else {
              response = await createApiKey(payload);
            }
            formikHelpers.setSubmitting(false);
            if (response.ok) {
              setPopup({
                message: isUpdate
                  ? "Successfully updated API key!"
                  : "Successfully created API key!",
                type: "success",
              });
              if (!isUpdate) {
                onCreateApiKey(await response.json());
              }
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: isUpdate
                  ? `Error updating API key - ${errorMsg}`
                  : `Error creating API key - ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form className="w-full overflow-visible">
              <Text className="mb-4 text-lg">
                Choose a memorable name for your API key. This is optional and
                can be added or changed later!
              </Text>

              <TextFormField
                name="name"
                label="Name (optional):"
                autoCompleteDisabled={true}
              />

              <SelectorFormField
                // defaultValue is managed by Formik
                label="Role:"
                subtext="Select the role for this API key.
                         Mirror My Permissions will inherit all your current permissions.
                         Limited has access to simple public API's.
                         Basic has access to regular user API's.
                         Admin has access to admin level APIs."
                name="role"
                options={[
                  {
                    name: "Mirror My Permissions",
                    value: MIRROR_ROLE_VALUE,
                  },
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

              <Button disabled={isSubmitting}>
                {isUpdate ? "Update" : "Create"}
              </Button>
            </Form>
          )}
        </Formik>
      </>
    </Modal>
  );
};
