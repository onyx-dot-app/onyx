import Modal from "@/refresh-components/Modal";
import { updateUserGroup } from "./lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { User, UserGroup } from "@/lib/types";
import { UserEditor } from "../UserEditor";
import { useState } from "react";
import { SvgUserPlus } from "@opal/icons";
export interface AddMemberFormProps {
  users: User[];
  userGroup: UserGroup;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec) => void;
}

export default function AddMemberForm({
  users,
  userGroup,
  onClose,
  setPopup,
}: AddMemberFormProps) {
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgUserPlus}
          title="Add New User"
          onClose={onClose}
        />
        <Modal.Body>
          <UserEditor
            selectedUserIds={selectedUserIds}
            setSelectedUserIds={setSelectedUserIds}
            allUsers={users}
            existingUsers={userGroup.users}
            onSubmit={async (selectedUsers) => {
              const newUserIds = [
                ...Array.from(
                  new Set(
                    userGroup.users
                      .map((user) => user.id)
                      .concat(selectedUsers.map((user) => user.id))
                  )
                ),
              ];
              const response = await updateUserGroup(userGroup.id, {
                user_ids: newUserIds,
                cc_pair_ids: userGroup.cc_pairs.map((ccPair) => ccPair.id),
              });
              if (response.ok) {
                setPopup({
                  message: "Successfully added users to group",
                  type: "success",
                });
                onClose();
              } else {
                const responseJson = await response.json();
                const errorMsg = responseJson.detail || responseJson.message;
                setPopup({
                  message: `Failed to add users to group - ${errorMsg}`,
                  type: "error",
                });
                onClose();
              }
            }}
          />
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
