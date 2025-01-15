import React, { useState } from "react";
import { MinimalUserSnapshot, User } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { FiPlus, FiX, FiEye, FiEyeOff } from "react-icons/fi";
import { SearchMultiSelectDropdown } from "@/components/Dropdown";
import { UsersIcon } from "@/components/icons/icons";
import { AssistantSharedStatusDisplay } from "../AssistantSharedStatus";
import {
  addUsersToAssistantSharedList,
  removeUsersFromAssistantSharedList,
} from "@/lib/assistants/shareAssistant";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Bubble } from "@/components/Bubble";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Spinner } from "@/components/Spinner";
import { useAssistants } from "@/components/context/AssistantsContext";
import { Separator } from "@/components/ui/separator";
import { Persona } from "@/app/admin/assistants/interfaces";
import { ThreeDotsLoader } from "@/components/Loading";

interface AssistantVisibilityPopoverProps {
  assistant: Persona;
  user: User | null;
  allUsers: MinimalUserSnapshot[];
  onClose: () => void;
  onTogglePublic: (isPublic: boolean) => Promise<void>;
}

export function AssistantVisibilityPopover({
  assistant,
  user,
  allUsers,
  onClose,
  onTogglePublic,
}: AssistantVisibilityPopoverProps) {
  const { refreshAssistants } = useAssistants();
  const { popup, setPopup } = usePopup();
  const [isUpdating, setIsUpdating] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState<MinimalUserSnapshot[]>([]);

  const assistantName = assistant.name;
  const sharedUsersWithoutOwner = (assistant.users || [])?.filter(
    (u: MinimalUserSnapshot) => u.id !== assistant.owner?.id
  );

  const handleShare = async () => {
    setIsUpdating(true);
    const startTime = Date.now();

    const error = await addUsersToAssistantSharedList(
      assistant,
      selectedUsers.map((user) => user.id)
    );
    await refreshAssistants();

    const elapsedTime = Date.now() - startTime;
    const remainingTime = Math.max(0, 1000 - elapsedTime);

    setTimeout(() => {
      setIsUpdating(false);
      if (error) {
        setPopup({
          message: `Failed to share assistant - ${error}`,
          type: "error",
        });
      }
    }, remainingTime);
  };

  const handleTogglePublic = async () => {
    setIsUpdating(true);
    await onTogglePublic(!assistant.is_public);
    setIsUpdating(false);
  };

  return (
    <>
      {popup}
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold mb-2">Visibility</h3>
          <Button
            onClick={handleTogglePublic}
            variant="outline"
            size="sm"
            className="w-full justify-start"
          >
            {assistant.is_public ? (
              <>
                <FiEyeOff className="mr-2" />
                Make Private
              </>
            ) : (
              <>
                <FiEye className="mr-2" />
                Make Public
              </>
            )}
            {isUpdating && (
              <div className="ml-2 inline-flex items-center">
                <ThreeDotsLoader />
                <span className="ml-2 text-sm text-gray-600">Updating...</span>
              </div>
            )}
          </Button>
        </div>

        <Separator />

        <div>
          <h3 className="text-sm font-semibold mb-2">Share</h3>
          <SearchMultiSelectDropdown
            options={allUsers
              .filter(
                (u1) =>
                  !selectedUsers.map((u2) => u2.id).includes(u1.id) &&
                  !sharedUsersWithoutOwner
                    .map((u2: MinimalUserSnapshot) => u2.id)
                    .includes(u1.id) &&
                  u1.id !== user?.id
              )
              .map((user) => ({
                name: user.email,
                value: user.id,
              }))}
            onSelect={(option) => {
              setSelectedUsers([
                ...Array.from(
                  new Set([
                    ...selectedUsers,
                    { id: option.value as string, email: option.name },
                  ])
                ),
              ]);
            }}
            itemComponent={({ option }) => (
              <div className="flex items-center px-4 py-2.5 cursor-pointer hover:bg-gray-100">
                <UsersIcon className="mr-3 text-gray-500" />
                <span className="flex-grow">{option.name}</span>
                <FiPlus className="text-blue-500" />
              </div>
            )}
          />
        </div>

        {selectedUsers.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-gray-700 mb-2">
              Selected Users:
            </h4>
            <div className="flex flex-wrap gap-2">
              {selectedUsers.map((selectedUser) => (
                <div
                  key={selectedUser.id}
                  onClick={() => {
                    setSelectedUsers(
                      selectedUsers.filter(
                        (user) => user.id !== selectedUser.id
                      )
                    );
                  }}
                  className="flex items-center bg-blue-50 text-blue-700 rounded-full px-3 py-1 text-xs hover:bg-blue-100 transition-colors duration-200 cursor-pointer"
                >
                  {selectedUser.email}
                  <FiX className="ml-2 text-blue-500" />
                </div>
              ))}
            </div>
          </div>
        )}

        {selectedUsers.length > 0 && (
          <Button
            onClick={() => {
              handleShare();
              setSelectedUsers([]);
            }}
            size="sm"
            variant="secondary"
          >
            Share with Selected Users
          </Button>
        )}

        <div>
          <h3 className="text-sm font-semibold mb-2">Currently Shared With</h3>
          <div className="bg-gray-50 rounded-lg p-2">
            <AssistantSharedStatusDisplay
              size="md"
              assistant={assistant}
              user={user}
            />
          </div>
        </div>
      </div>
    </>
  );
}
