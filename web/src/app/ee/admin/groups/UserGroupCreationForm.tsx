import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConnectorStatus, User, UserGroup } from "@/lib/types";
import { TextFormField } from "@/components/admin/connectors/Field";
import { createUserGroup } from "./lib";
import { UserEditor } from "./UserEditor";
import { ConnectorEditor } from "./ConnectorEditor";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface UserGroupCreationFormProps {
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  users: User[];
  ccPairs: ConnectorStatus<any, any>[];
  existingUserGroup?: UserGroup;
}

export const UserGroupCreationForm = ({
  onClose,
  setPopup,
  users,
  ccPairs,
  existingUserGroup,
}: UserGroupCreationFormProps) => {
  const isUpdate = existingUserGroup !== undefined;

  // Filter out ccPairs that aren't access_type "private"
  const privateCcPairs = ccPairs.filter(
    (ccPair) => ccPair.access_type === "private"
  );

  return (
    <Modal className="w-fit" onOutsideClick={onClose}>
      <>
        <h2 className="text-xl font-bold flex">
          {isUpdate
            ? i18n.t(k.UPDATE_A_USER_GROUP)
            : i18n.t(k.CREATE_A_NEW_USER_GROUP)}
        </h2>

        <Separator />

        <Formik
          initialValues={{
            name: existingUserGroup ? existingUserGroup.name : "",
            user_ids: [] as string[],
            cc_pair_ids: [] as number[],
          }}
          validationSchema={Yup.object().shape({
            name: Yup.string().required(i18n.t(k.PLEASE_ENTER_GROUP_NAME)),
            user_ids: Yup.array().of(Yup.string().required()),
            cc_pair_ids: Yup.array().of(Yup.number().required()),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);
            let response;
            response = await createUserGroup(values);
            formikHelpers.setSubmitting(false);
            if (response.ok) {
              setPopup({
                message: isUpdate
                  ? i18n.t(k.SUCCESSFULLY_UPDATED_USER_GROU)
                  : i18n.t(k.SUCCESSFULLY_CREATED_USER_GROU),

                type: "success",
              });
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: isUpdate
                  ? `${i18n.t(k.ERROR_UPDATING_USER_GROUP)} ${errorMsg}`
                  : `${i18n.t(k.ERROR_CREATING_USER_GROUP)} ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form>
              <div className="py-4">
                <TextFormField
                  name="name"
                  label={i18n.t(k.GROUP_NAME_LABEL)}
                  placeholder={i18n.t(k.GROUP_NAME_PLACEHOLDER)}
                  disabled={isUpdate}
                  autoCompleteDisabled={true}
                />

                <Separator />

                <h2 className="mb-1 font-medium">
                  {i18n.t(k.SELECT_WHICH_PRIVATE_CONNECTOR)}
                </h2>
                <p className="mb-3 text-xs">
                  {i18n.t(k.ALL_DOCUMENTS_INDEXED_BY_THE_S)}
                </p>

                <ConnectorEditor
                  allCCPairs={privateCcPairs}
                  selectedCCPairIds={values.cc_pair_ids}
                  setSetCCPairIds={(ccPairsIds) =>
                    setFieldValue("cc_pair_ids", ccPairsIds)
                  }
                />

                <Separator />

                <h2 className="mb-1 font-medium">
                  {i18n.t(k.SELECT_WHICH_USERS_SHOULD_BE_A)}
                </h2>
                <p className="mb-3 text-xs">
                  {i18n.t(k.ALL_SELECTED_USERS_WILL_BE_ABL)}
                </p>
                <div className="mb-3 gap-2">
                  <UserEditor
                    selectedUserIds={values.user_ids}
                    setSelectedUserIds={(userIds) =>
                      setFieldValue("user_ids", userIds)
                    }
                    allUsers={users}
                    existingUsers={[]}
                  />
                </div>
                <div className="flex">
                  <Button
                    type="submit"
                    size="sm"
                    variant="submit"
                    disabled={isSubmitting}
                    className="mx-auto w-64"
                  >
                    {isUpdate ? i18n.t(k.UPDATE1) : i18n.t(k.CREATE)}
                  </Button>
                </div>
              </div>
            </Form>
          )}
        </Formik>
      </>
    </Modal>
  );
};
