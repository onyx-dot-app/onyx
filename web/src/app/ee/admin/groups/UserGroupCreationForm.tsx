import { Form, Formik } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConnectorStatus, User, UserGroup } from "@/lib/types";
import { TextFormField } from "@/components/Field";
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
          {isUpdate ? "Update a User Group" : "Create a new User Group"}
        </h2>

        <Separator />

        <Formik
          initialValues={{
            name: existingUserGroup ? existingUserGroup.name : "",
            user_ids: [] as string[],
            cc_pair_ids: [] as number[],
          }}
          validationSchema={Yup.object().shape({
            name: Yup.string().required("Please enter a name for the group"),
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
                  ? "Successfully updated user group!"
                  : "Successfully created user group!",
                type: "success",
              });
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: isUpdate
                  ? `Error updating user group - ${errorMsg}`
                  : `Error creating user group - ${errorMsg}`,
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
                  label="Name:"
                  placeholder="A name for the User Group"
                  disabled={isUpdate}
                  autoCompleteDisabled={true}
                />

                <Separator />

                <h2 className="mb-1 font-medium">
                  Select which private connectors this group has access to:
                </h2>
                <p className="mb-3 text-xs">
                  All documents indexed by the selected connectors will be
                  visible to users in this group.
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
                  Select which Users should be a part of this Group.
                </h2>
                <p className="mb-3 text-xs">
                  All selected users will be able to search through all
                  documents indexed by the selected connectors.
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
                    {isUpdate ? "Update!" : "Create!"}
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
