import Modal from "@/refresh-components/Modal";
import { updateUserGroup } from "./lib";
import { toast } from "@/hooks/useToast";
import { User, UserGroup } from "@/lib/types";
import { UserEditor } from "../UserEditor";
import { useState } from "react";
import { SvgUserPlus } from "@opal/icons";
export interface AddMemberFormProps {
  users: User[];
  userGroup: UserGroup;
  onClose: () => void;
}

export default function AddMemberForm({
  users,
  userGroup,
  onClose,
}: AddMemberFormProps) {
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm" height="sm">
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
                toast.success("Successfully added users to group");
                onClose();
              } else {
                const responseJson = await response.json();
                const errorMsg = responseJson.detail || responseJson.message;
                toast.error(`Failed to add users to group - ${errorMsg}`);
                onClose();
              }
            }}
          />
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
