import { Form, Formik } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { createApiKey, updateApiKey } from "./lib";
import { Modal } from "@/components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import {
  APIKey,
  CreateAPIKeyArgs,
  UpdateAPIKeyArgs,
  ApiKeyType,
} from "./types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useState } from "react";

interface OnyxApiKeyFormProps {
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  onCreateApiKey: (apiKey: APIKey) => void;
  apiKey?: APIKey;
}

const ApiKeyNameField = () => (
  <TextFormField
    name="name"
    label="Name (optional):"
    subtext="Choose a memorable name for your API key. This is optional and can be added or changeed later!"
    autoCompleteDisabled={true}
  />
);

const ApiKeyRoleSelector = () => (
  <SelectorFormField
    label="Role:"
    subtext="Select the role for this service account.
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
);

const PersonalAccessTokenForm = () => (
  <>
    <Text className="mb-4 text-lg">
      API key that mirrors your own permissions and access to resources.
    </Text>

    <ApiKeyNameField />
  </>
);

const ServiceAccountKeyForm = () => (
  <>
    <Text className="mb-4 text-lg">
      API key for a service account with a specific role.
    </Text>

    <div className="space-y-4">
      <ApiKeyNameField />
      <ApiKeyRoleSelector />
    </div>
  </>
);

export const OnyxApiKeyForm = ({
  onClose,
  setPopup,
  onCreateApiKey,
  apiKey,
}: OnyxApiKeyFormProps) => {
  const isUpdate = apiKey !== undefined;
  const isExistingPAT =
    apiKey?.api_key_type === ApiKeyType.PERSONAL_ACCESS_TOKEN;

  // Tab state - only relevant for create mode (tabs are hidden when updating)
  const [selectedTab, setSelectedTab] = useState<"personal" | "service">(
    "personal"
  );

  return (
    <Modal onOutsideClick={onClose} width="w-2/6">
      <>
        <h2 className="text-xl font-bold flex">
          {isUpdate
            ? `Update ${
                isExistingPAT ? "Personal Access Token" : "Service Account Key"
              }`
            : "Create a new API Key"}
        </h2>

        <Separator />

        <Formik
          initialValues={{
            name: apiKey?.api_key_name || "",
            role: apiKey?.api_key_role || UserRole.BASIC,
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            let response;
            if (isUpdate) {
              // UPDATE MODE: Use UpdateAPIKeyArgs
              const updatePayload: UpdateAPIKeyArgs = {
                name: values.name,
                role: isExistingPAT ? undefined : values.role,
              };
              response = await updateApiKey(apiKey.api_key_id, updatePayload);
            } else {
              // CREATE MODE: Use CreateAPIKeyArgs
              const apiKeyType =
                selectedTab === "personal"
                  ? ApiKeyType.PERSONAL_ACCESS_TOKEN
                  : ApiKeyType.SERVICE_ACCOUNT;

              const createPayload: CreateAPIKeyArgs = {
                type: apiKeyType,
                name: values.name,
                role:
                  apiKeyType === ApiKeyType.SERVICE_ACCOUNT
                    ? values.role
                    : undefined,
              };
              response = await createApiKey(createPayload);
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
              {isUpdate ? (
                // EDIT MODE: Show only the relevant form without tabs
                <div>
                  {isExistingPAT ? (
                    <PersonalAccessTokenForm />
                  ) : (
                    <ServiceAccountKeyForm />
                  )}
                </div>
              ) : (
                // CREATE MODE: Show tabs with both options
                <Tabs
                  defaultValue="personal"
                  value={selectedTab}
                  onValueChange={(value) =>
                    setSelectedTab(value as "personal" | "service")
                  }
                  className="w-full"
                >
                  <TabsList className="mb-4 w-full">
                    <TabsTrigger value="personal" className="flex-1">
                      Personal Access Token
                    </TabsTrigger>
                    <TabsTrigger value="service" className="flex-1">
                      Service Account Key
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="personal">
                    <PersonalAccessTokenForm />
                  </TabsContent>

                  <TabsContent value="service">
                    <ServiceAccountKeyForm />
                  </TabsContent>
                </Tabs>
              )}

              <Button disabled={isSubmitting} className="mt-4">
                {isUpdate ? "Update" : "Create"}
              </Button>
            </Form>
          )}
        </Formik>
      </>
    </Modal>
  );
};
