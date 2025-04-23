import { User } from "@/lib/types";
import { FiPlus, FiX } from "react-icons/fi";
import { SearchMultiSelectDropdown } from "@/components/Dropdown";
import { UsersIcon } from "@/components/icons/icons";
import { Button } from "@/components/ui/button";

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
        <SearchMultiSelectDropdown
          options={allUsers
            .filter(
              (user) =>
                !selectedUserIds.includes(user.id) &&
                !existingUsers.map((user) => user.id).includes(user.id)
            )
            .map((user) => {
              return {
                name: user.email,
                value: user.id,
              };
            })}
          onSelect={(option) => {
            setSelectedUserIds([
              ...Array.from(
                new Set([...selectedUserIds, option.value as string])
              ),
            ]);
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
