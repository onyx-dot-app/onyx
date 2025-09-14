"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../../i18n/keys";
import { Modal } from "@/components/Modal";
import { updateUserGroup } from "./lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { User, UserGroup } from "@/lib/types";
import { UserEditor } from "../UserEditor";
import { useState } from "react";

interface AddMemberFormProps {
  users: User[];
  userGroup: UserGroup;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec) => void;
}

export const AddMemberForm: React.FC<AddMemberFormProps> = ({
  users,
  userGroup,
  onClose,
  setPopup,
}) => {
  const { t } = useTranslation();
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);

  return (
    <Modal
      className="max-w-xl overflow-visible"
      title={t(k.ADD_NEW_USER)}
      onOutsideClick={() => onClose()}
    >
      <div className="flex flex-col">
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
                message: t(k.SUCCESSFULLY_ADDED_USERS_TO_GR),
                type: "success",
              });
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: `${t(k.FAILED_TO_ADD_USERS_TO_GROUP)} ${errorMsg}`,
                type: "error",
              });
              onClose();
            }
          }}
        />
      </div>
    </Modal>
  );
};
