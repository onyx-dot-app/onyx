import { Form, Formik } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { TextFormField } from "@/components/Field";
import { Modal } from "@/refresh-components/modals/NewModal";
import Button from "@/refresh-components/buttons/Button";
import { Separator } from "@/components/ui/separator";
import { Callout } from "@/components/ui/callout";
import Text from "@/refresh-components/texts/Text";
import {
  OAuthConfig,
  OAuthConfigCreate,
  OAuthConfigUpdate,
} from "@/lib/tools/interfaces";
import { createOAuthConfig, updateOAuthConfig } from "@/lib/oauth/api";
import * as Yup from "yup";

interface OAuthConfigFormProps {
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  config?: OAuthConfig;
  onConfigSubmitted?: (config: OAuthConfig) => void;
}

const OAuthConfigSchema = Yup.object().shape({
  name: Yup.string().required("Name is required"),
  authorization_url: Yup.string()
    .url("Must be a valid URL")
    .required("Authorization URL is required"),
  token_url: Yup.string()
    .url("Must be a valid URL")
    .required("Token URL is required"),
  client_id: Yup.string().when("isUpdate", {
    is: false,
    then: (schema) => schema.required("Client ID is required"),
    otherwise: (schema) => schema,
  }),
  client_secret: Yup.string().when("isUpdate", {
    is: false,
    then: (schema) => schema.required("Client Secret is required"),
    otherwise: (schema) => schema,
  }),
  scopes: Yup.string(),
});

export const OAuthConfigForm = ({
  onClose,
  setPopup,
  config,
  onConfigSubmitted,
}: OAuthConfigFormProps) => {
  const isUpdate = config !== undefined;

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      onClose();
    }
  };

  return (
    <Modal open onOpenChange={handleOpenChange}>
      <Modal.Content
        className="w-[60%] max-h-[calc(100dvh-4rem)]"
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          // Use setTimeout to wait for Formik to render the inputs
          setTimeout(() => {
            const firstInput =
              document.querySelector<HTMLInputElement>('input[name="name"]');
            if (firstInput) {
              firstInput.focus();
            }
          }, 0);
        }}
      >
        <Modal.CloseButton />

        <Modal.Header className="px-6 pt-6 pb-4">
          <Modal.Title className="font-heading-h2">
            {isUpdate
              ? "Update OAuth Configuration"
              : "Create OAuth Configuration"}
          </Modal.Title>
          <Separator />
        </Modal.Header>
        <Formik
          initialValues={{
            name: config?.name || "",
            authorization_url: config?.authorization_url || "",
            token_url: config?.token_url || "",
            client_id: "",
            client_secret: "",
            scopes: config?.scopes?.join(", ") || "",
            isUpdate,
          }}
          validationSchema={OAuthConfigSchema}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            try {
              // Parse scopes from comma-separated string
              const scopesArray = values.scopes
                .split(",")
                .map((s) => s.trim())
                .filter((s) => s.length > 0);

              if (isUpdate && config) {
                // Build update payload - only include fields that are provided
                const updatePayload: OAuthConfigUpdate = {
                  name: values.name,
                  authorization_url: values.authorization_url,
                  token_url: values.token_url,
                  scopes: scopesArray,
                };

                // Only include client credentials if they are provided
                if (values.client_id) {
                  updatePayload.client_id = values.client_id;
                }
                if (values.client_secret) {
                  updatePayload.client_secret = values.client_secret;
                }

                const updatedConfig = await updateOAuthConfig(
                  config.id,
                  updatePayload
                );
                setPopup({
                  message: "Successfully updated OAuth configuration!",
                  type: "success",
                });

                // Call the callback to refresh the list
                if (onConfigSubmitted) {
                  onConfigSubmitted(updatedConfig);
                }
              } else {
                // Create new config
                const createPayload: OAuthConfigCreate = {
                  name: values.name,
                  authorization_url: values.authorization_url,
                  token_url: values.token_url,
                  client_id: values.client_id,
                  client_secret: values.client_secret,
                  scopes: scopesArray,
                };

                const createdConfig = await createOAuthConfig(createPayload);
                setPopup({
                  message: "Successfully created OAuth configuration!",
                  type: "success",
                });

                // Call the callback with the created config
                if (onConfigSubmitted && createdConfig) {
                  onConfigSubmitted(createdConfig);
                }
              }
              onClose();
            } catch (error: any) {
              setPopup({
                message: isUpdate
                  ? `Error updating OAuth configuration - ${error.message}`
                  : `Error creating OAuth configuration - ${error.message}`,
                type: "error",
              });
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form className="flex flex-col flex-1 overflow-hidden w-full">
              <Modal.Body className="flex-1 overflow-y-auto px-6 pb-4 space-y-4 w-full">
                <Text>
                  Configure an OAuth provider that can be shared across multiple
                  custom tools. Users will authenticate with this provider when
                  using tools that require it.
                </Text>

                <Callout
                  type="notice"
                  icon="📋"
                  title="Redirect URI for OAuth App Configuration"
                >
                  <Text className="text-sm mb-2">
                    When configuring your OAuth application in the
                    provider&apos;s dashboard, use this redirect URI:
                  </Text>
                  <code className="block p-2 bg-background-100 rounded text-sm font-mono">
                    {typeof window !== "undefined"
                      ? `${window.location.origin}/oauth-config/callback`
                      : "{YOUR_DOMAIN}/oauth-config/callback"}
                  </code>
                </Callout>

                <TextFormField
                  name="name"
                  label="Configuration Name:"
                  subtext="A friendly name to identify this OAuth configuration (e.g., 'GitHub OAuth', 'Google OAuth')"
                  placeholder="e.g., GitHub OAuth"
                  autoCompleteDisabled={true}
                />

                <TextFormField
                  name="authorization_url"
                  label="Authorization URL:"
                  subtext="The OAuth provider's authorization endpoint"
                  placeholder="e.g., https://github.com/login/oauth/authorize"
                  autoCompleteDisabled={true}
                />

                <TextFormField
                  name="token_url"
                  label="Token URL:"
                  subtext="The OAuth provider's token exchange endpoint"
                  placeholder="e.g., https://github.com/login/oauth/access_token"
                  autoCompleteDisabled={true}
                />

                <TextFormField
                  name="client_id"
                  label={isUpdate ? "Client ID (optional):" : "Client ID:"}
                  subtext={
                    isUpdate
                      ? "Leave empty to keep existing client ID"
                      : "Your OAuth application's client ID"
                  }
                  placeholder={
                    isUpdate
                      ? "Enter new client ID to update"
                      : "Your client ID"
                  }
                  autoCompleteDisabled={true}
                />

                <TextFormField
                  name="client_secret"
                  label={
                    isUpdate ? "Client Secret (optional):" : "Client Secret:"
                  }
                  subtext={
                    isUpdate
                      ? "Leave empty to keep existing client secret"
                      : "Your OAuth application's client secret"
                  }
                  placeholder={
                    isUpdate
                      ? "Enter new client secret to update"
                      : "Your client secret"
                  }
                  type="password"
                  autoCompleteDisabled={true}
                />

                <TextFormField
                  name="scopes"
                  label="Scopes (optional):"
                  subtext="Comma-separated list of OAuth scopes to request (e.g., 'repo, user')"
                  placeholder="e.g., repo, user"
                  autoCompleteDisabled={true}
                />
              </Modal.Body>

              <Modal.Footer className="flex gap-2 px-6 py-4 w-full">
                <Button type="submit" disabled={isSubmitting} primary>
                  {isUpdate ? "Update" : "Create"}
                </Button>
                <Button
                  type="button"
                  onClick={onClose}
                  disabled={isSubmitting}
                  secondary
                >
                  Cancel
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
};
