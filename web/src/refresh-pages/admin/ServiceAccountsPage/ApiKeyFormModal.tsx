"use client";

import { Form, Formik } from "formik";
import { toast } from "@/hooks/useToast";
import {
  createApiKey,
  updateApiKey,
} from "@/refresh-pages/admin/ServiceAccountsPage/svc";
import type { APIKey } from "@/refresh-pages/admin/ServiceAccountsPage/interfaces";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { SvgKey } from "@opal/icons";

interface ApiKeyFormModalProps {
  onClose: () => void;
  onCreateApiKey: (apiKey: APIKey) => void;
  apiKey?: APIKey;
}

export default function ApiKeyFormModal({
  onClose,
  onCreateApiKey,
  apiKey,
}: ApiKeyFormModalProps) {
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

            const payload = {
              ...values,
              role: values.role as UserRole,
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
                        <InputSelect
                          value={field.value}
                          onValueChange={(value) => helper.setValue(value)}
                        >
                          <InputSelect.Trigger placeholder="Select a role" />
                          <InputSelect.Content>
                            <InputSelect.Item
                              value={UserRole.LIMITED.toString()}
                            >
                              {USER_ROLE_LABELS[UserRole.LIMITED]}
                            </InputSelect.Item>
                            <InputSelect.Item value={UserRole.BASIC.toString()}>
                              {USER_ROLE_LABELS[UserRole.BASIC]}
                            </InputSelect.Item>
                            <InputSelect.Item value={UserRole.ADMIN.toString()}>
                              {USER_ROLE_LABELS[UserRole.ADMIN]}
                            </InputSelect.Item>
                          </InputSelect.Content>
                        </InputSelect>
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
                <Disabled disabled={isSubmitting}>
                  <Button type="submit">
                    {isUpdate ? "Update" : "Create"}
                  </Button>
                </Disabled>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
