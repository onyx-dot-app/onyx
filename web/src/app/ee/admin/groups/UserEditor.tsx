import { User } from "@/lib/types";
import { FiX } from "react-icons/fi";
import InputComboBox from "@/refresh-components/inputs/InputComboBox/InputComboBox";
import Button from "@/refresh-components/buttons/Button";

interface UserEditorProps {
  selectedUserIds: string[];
  setSelectedUserIds: (userIds: string[]) => void;
  allUsers: User[];
  existingUsers: User[];
  onSubmit?: (users: User[]) => void;
}

export const UserEditor = ({
  selectedUserIds,
  setSelectedUserIds,
  allUsers,
  existingUsers,
  onSubmit,
}: UserEditorProps) => {
  const selectedUsers = allUsers.filter((user) =>
    selectedUserIds.includes(user.id)
  );

  return (
    <>
      <div className="mb-2 flex flex-wrap gap-x-2">
        {selectedUsers.length > 0 &&
          selectedUsers.map((selectedUser) => (
            <div
              key={selectedUser.id}
              onClick={() => {
                setSelectedUserIds(
                  selectedUserIds.filter((userId) => userId !== selectedUser.id)
                );
              }}
              className={`
                  flex
                  rounded-lg
                  px-2
                  py-1
                  border
                  border-border
                  hover:bg-accent-background
                  cursor-pointer`}
            >
              {selectedUser.email} <FiX className="ml-1 my-auto" />
            </div>
          ))}
      </div>

      <div className="flex">
        <InputComboBox
          placeholder="Search..."
          value=""
          onChange={() => {}}
          onValueChange={(selectedValue) => {
            setSelectedUserIds([
              ...Array.from(new Set([...selectedUserIds, selectedValue])),
            ]);
          }}
          options={allUsers
            .filter(
              (user) =>
                !selectedUserIds.includes(user.id) &&
                !existingUsers.map((user) => user.id).includes(user.id)
            )
            .map((user) => ({
              label: user.email,
              value: user.id,
            }))}
          strict
          leftSearchIcon
        />
        {onSubmit && (
          <Button
            className="ml-3 flex-nowrap w-32"
            onClick={() => onSubmit(selectedUsers)}
          >
            Add Users
          </Button>
        )}
      </div>
    </>
  );
};
