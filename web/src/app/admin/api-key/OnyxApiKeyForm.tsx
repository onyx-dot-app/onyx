"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import { Form, Formik } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  BooleanFormField,
  SelectorFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { createApiKey, updateApiKey } from "./lib";
import { FiPlus, FiX } from "react-icons/fi";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { APIKey } from "./types";
import { SearchMultiSelectDropdown } from "@/components/Dropdown";
import { useUsers } from "@/lib/hooks";
import { UsersIcon } from "@/components/icons/icons";
import { useState, useEffect } from "react";

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
  const { t } = useTranslation();
  const isUpdate = apiKey !== undefined;

  const {
    data: users,
    isLoading: userIsLoading,
    error: usersError,
  } = useUsers({ includeApiKeys: true });

  const [selectedUser, setSelectedUser] = useState<
    | {
        name: string;
        value: string;
      }
    | undefined
  >(undefined);

  useEffect(() => {
    if (isUpdate && apiKey?.user_id && users?.accepted) {
      const user = users.accepted.find((u) => u.id === apiKey.user_id);
      if (user) {
        setSelectedUser({
          name: user.email,
          value: apiKey.user_id,
        });
      }
    }
  }, [isUpdate, apiKey?.user_id, users]);

  const showRoleField = isUpdate ? apiKey?.is_new_user === true : !selectedUser;

  return (
    <Modal onOutsideClick={onClose} width="w-2/6">
      <>
        <h2 className="text-xl font-bold flex">
          {isUpdate ? t(k.UPDATE_API_KEY) : t(k.CREATE_A_NEW_API_KEY)}
        </h2>

        <Separator />

        <Formik
          initialValues={{
            name: apiKey?.api_key_name || "",
            role: apiKey?.api_key_role || UserRole.BASIC.toString(),
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            const payload: {
              name?: string;
              role?: UserRole;
              user_id?: string;
            } = {
              name: values.name || undefined,
            };

            if (isUpdate) {
              if (apiKey?.is_new_user) {
                payload.role = values.role as UserRole;
              }
            } else {
              if (!selectedUser) {
                payload.role = values.role as UserRole;
              } else {
                payload.user_id = selectedUser.value;
              }
            }

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
                  ? t(k.SUCCESSFULLY_UPDATED_API_KEY)
                  : t(k.SUCCESSFULLY_CREATED_API_KEY),

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
                  ? `${t(k.ERROR_UPDATING_API_KEY)} ${errorMsg}`
                  : `${t(k.ERROR_CREATING_API_KEY)} ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form className="w-full overflow-visible">
              <Text className="mb-4 text-lg">
                {t(k.CHOOSE_A_MEMORABLE_NAME_FOR_YO)}
              </Text>

              <TextFormField
                name="name"
                label={t(k.API_KEY_NAME_LABEL)}
                autoCompleteDisabled={true}
              />

              {showRoleField && (
                <SelectorFormField
                  label={t(k.ROLE_LABEL)}
                  subtext={t(k.ROLE_SUBTEXT)}
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
              )}

              {isUpdate && selectedUser && (
                <div className="mb-4">
                  <Text className="mb-2 text-sm font-medium">
                    {t(k.ATTACHED_USER)}
                  </Text>
                  <div className="flex items-center bg-blue-50 text-blue-700 rounded-lg px-3 py-2 text-sm">
                    <UsersIcon className="mr-2" />
                    {selectedUser.name}
                  </div>
                  <Text className="mt-2 text-xs text-text-600">
                    {apiKey?.is_new_user
                      ? t(k.API_KEY_NEW_USER_DESC)
                      : t(k.API_KEY_EXISTING_USER_DESC)}
                  </Text>
                </div>
              )}

              {!isUpdate && (
                <div className="mb-4">
                  <Text className="mb-2 text-sm font-medium">
                    {t(k.SELECT_USER_OPTIONAL)}
                  </Text>
                  <Text className="mb-2 text-xs text-text-600">
                    {selectedUser
                      ? t(k.SELECT_USER_EXISTING_DESC)
                      : t(k.SELECT_USER_NEW_DESC)}
                  </Text>
                </div>
              )}

              {!isUpdate && (
                <SearchMultiSelectDropdown
                  options={
                    !userIsLoading && users
                      ? users.accepted
                          .filter((user) => selectedUser?.value !== user.id)
                          .filter((user) => !user.email.includes("api_key"))
                          .map((user) => {
                            return {
                              name: user.email,
                              value: user.id,
                            };
                          })
                      : []
                  }
                  onSelect={(option) => {
                    // @ts-ignore
                    setSelectedUser(option);
                  }}
                  itemComponent={({ option }) => (
                    <div className="flex px-4 py-2.5 cursor-pointer hover:bg-accent-background-hovered">
                      <UsersIcon className="mr-2 my-auto" />
                      {option.name}
                      <div className="ml-auto my-auto">
                        <FiPlus />
                      </div>
                    </div>
                  )}
                />
              )}

              {!isUpdate && selectedUser?.name && (
                <div className="mb-6">
                  <h4 className="text-sm font-medium text-text-700 mb-2">
                    {t(k.SELECTED_USERS)}
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    <div
                      key={selectedUser?.value}
                      onClick={() => {
                        setSelectedUser(undefined);
                      }}
                      className="flex items-center bg-blue-50 text-blue-700 rounded-full px-3 py-1 text-sm hover:bg-blue-100 transition-colors duration-200 cursor-pointer"
                    >
                      {selectedUser?.name}
                      <FiX className="ml-2 text-blue-500" />
                    </div>
                  </div>
                </div>
              )}

              <Button
                type="submit"
                size="sm"
                variant="submit"
                disabled={isSubmitting}
              >
                {isUpdate ? t(k.UPDATE1) : t(k.CREATE)}
              </Button>
            </Form>
          )}
        </Formik>
      </>
    </Modal>
  );
};
