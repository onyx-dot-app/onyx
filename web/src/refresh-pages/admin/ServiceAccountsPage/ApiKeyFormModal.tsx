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
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { FormikField } from "@/refresh-components/form/FormikField";
import { InputVertical } from "@opal/layouts";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { SvgKey, SvgLock, SvgUser, SvgUserManage } from "@opal/icons";

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
          title={isUpdate ? "Update Service Account" : "Create Service Account"}
          description={
            isUpdate
              ? undefined
              : "Use service account API key to programmatically access Onyx API with user-level permissions. You can modify the account details later."
          }
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

            try {
              let response;
              if (isUpdate) {
                response = await updateApiKey(apiKey.api_key_id, payload);
              } else {
                response = await createApiKey(payload);
              }
              if (response.ok) {
                toast.success(
                  isUpdate
                    ? "Successfully updated service account!"
                    : "Successfully created service account!"
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
                    ? `Error updating service account - ${errorMsg}`
                    : `Error creating service account - ${errorMsg}`
                );
              }
            } catch (e) {
              toast.error(
                e instanceof Error ? e.message : "An unexpected error occurred."
              );
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, values }) => (
            <Form className="w-full overflow-visible">
              <Modal.Body>
                <InputVertical withLabel="name" title="Name">
                  <FormikField<string>
                    name="name"
                    render={(field, helper) => (
                      <InputTypeIn
                        {...field}
                        placeholder="Enter a name"
                        onClear={() => helper.setValue("")}
                        showClearButton={false}
                      />
                    )}
                  />
                </InputVertical>

                <InputVertical withLabel="role" title="Account Permissions">
                  <FormikField<string>
                    name="role"
                    render={(field, helper) => (
                      <InputSelect
                        value={field.value}
                        onValueChange={(value) => helper.setValue(value)}
                      >
                        <InputSelect.Trigger placeholder="Select permissions" />
                        <InputSelect.Content>
                          <InputSelect.Item
                            value={UserRole.ADMIN.toString()}
                            icon={SvgUserManage}
                            description="Unrestricted admin access to all endpoints."
                          >
                            {USER_ROLE_LABELS[UserRole.ADMIN]}
                          </InputSelect.Item>
                          <InputSelect.Item
                            value={UserRole.BASIC.toString()}
                            icon={SvgUser}
                            description="Standard user-level access to non-admin endpoints."
                          >
                            {USER_ROLE_LABELS[UserRole.BASIC]}
                          </InputSelect.Item>
                          <InputSelect.Item
                            value={UserRole.LIMITED.toString()}
                            icon={SvgLock}
                            description="For agents: chat posting and read-only access to other endpoints."
                          >
                            {USER_ROLE_LABELS[UserRole.LIMITED]}
                          </InputSelect.Item>
                        </InputSelect.Content>
                      </InputSelect>
                    )}
                  />
                </InputVertical>
              </Modal.Body>

              <Modal.Footer>
                <Button prominence="secondary" type="button" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  disabled={isSubmitting || !values.name.trim()}
                  type="submit"
                >
                  {isUpdate ? "Update" : "Create Account"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
