"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { AddMemberForm } from "./AddMemberForm";
import { updateUserGroup, updateCuratorStatus } from "./lib";
import { LoadingAnimation } from "@/components/Loading";
import {
  User,
  UserGroup,
  UserRole,
  USER_ROLE_LABELS,
  ConnectorStatus,
} from "@/lib/types";
import { AddConnectorForm } from "./AddConnectorForm";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import Text from "@/components/ui/text";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { DeleteButton } from "@/components/DeleteButton";
import { Bubble } from "@/components/Bubble";
import { BookmarkIcon, RobotIcon } from "@/components/icons/icons";
import { AddTokenRateLimitForm } from "./AddTokenRateLimitForm";
import { GenericTokenRateLimitTable } from "@/app/admin/token-rate-limits/TokenRateLimitTables";
import { useUser } from "@/components/user/UserProvider";
import { GenericConfirmModal } from "@/components/modals/GenericConfirmModal";

interface GroupDisplayProps {
  users: User[];
  ccPairs: ConnectorStatus<any, any>[];
  userGroup: UserGroup;
  refreshUserGroup: () => void;
}

const UserRoleDropdown = ({
  user,
  group,
  onSuccess,
  onError,
  isAdmin,
}: {
  user: User;
  group: UserGroup;
  onSuccess: () => void;
  onError: (message: string) => void;
  isAdmin: boolean;
}) => {
  const [localRole, setLocalRole] = useState(() => {
    if (user.role === UserRole.CURATOR) {
      return group.curator_ids.includes(user.id)
        ? UserRole.CURATOR
        : UserRole.BASIC;
    }
    return user.role;
  });
  const [isSettingRole, setIsSettingRole] = useState(false);
  const [showDemoteConfirm, setShowDemoteConfirm] = useState(false);
  const [pendingRoleChange, setPendingRoleChange] = useState<string | null>(
    null
  );
  const { user: currentUser } = useUser();

  const applyRoleChange = async (value: string) => {
    if (value === localRole) return;
    if (value === UserRole.BASIC || value === UserRole.CURATOR) {
      setIsSettingRole(true);
      setLocalRole(value);
      try {
        const response = await updateCuratorStatus(group.id, {
          user_id: user.id,
          is_curator: value === UserRole.CURATOR,
        });
        if (response.ok) {
          onSuccess();
          user.role = value;
        } else {
          const errorData = await response.json();
          throw new Error(errorData.detail || "Failed to update user role");
        }
      } catch (error: any) {
        onError(error.message);
        setLocalRole(user.role);
      } finally {
        setIsSettingRole(false);
      }
    }
  };

  const handleChange = (value: string) => {
    if (value === UserRole.BASIC && user.id === currentUser?.id) {
      setPendingRoleChange(value);
      setShowDemoteConfirm(true);
    } else {
      applyRoleChange(value);
    }
  };

  const isEditable =
    user.role === UserRole.BASIC || user.role === UserRole.CURATOR;

  return (
    <>
      {/* Confirmation modal - only shown when users try to demote themselves */}
      {showDemoteConfirm && pendingRoleChange && (
        <GenericConfirmModal
          title="Remove Yourself as a Curator for this Group?"
          message="Are you sure you want to change your role to Basic? This will remove your ability to curate this group."
          confirmText="Yes, set me to Basic"
          onClose={() => {
            // Cancel the role change if user dismisses modal
            setShowDemoteConfirm(false);
            setPendingRoleChange(null);
          }}
          onConfirm={() => {
            // Apply the role change if user confirms
            setShowDemoteConfirm(false);
            applyRoleChange(pendingRoleChange);
            setPendingRoleChange(null);
          }}
        />
      )}

      {isEditable ? (
        <div className="w-40">
          <Select
            value={localRole}
            onValueChange={handleChange}
            disabled={isSettingRole}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select role" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UserRole.BASIC}>Basic</SelectItem>
              <SelectItem value={UserRole.CURATOR}>Curator</SelectItem>
            </SelectContent>
          </Select>
        </div>
      ) : (
        <div>{USER_ROLE_LABELS[localRole]}</div>
      )}
    </>
  );
};

export const GroupDisplay = ({
  users,
  ccPairs,
  userGroup,
  refreshUserGroup,
}: GroupDisplayProps) => {
  const { popup, setPopup } = usePopup();
  const [addMemberFormVisible, setAddMemberFormVisible] = useState(false);
  const [addConnectorFormVisible, setAddConnectorFormVisible] = useState(false);
  const [addRateLimitFormVisible, setAddRateLimitFormVisible] = useState(false);

  const { isAdmin } = useUser();

  const handlePopup = (message: string, type: "success" | "error") => {
    setPopup({ message, type });
  };

  const onRoleChangeSuccess = () =>
    handlePopup("User role updated successfully!", "success");
  const onRoleChangeError = (errorMsg: string) =>
    handlePopup(`Unable to update user role - ${errorMsg}`, "error");

  return (
    <div>
      {popup}

      <div className="text-sm mb-3 flex">
        <Text className="mr-1">Status:</Text>{" "}
        {userGroup.is_up_to_date ? (
          <div className="text-success font-bold">Up to date</div>
        ) : (
          <div className="text-accent font-bold">
            <LoadingAnimation text="Syncing" />
          </div>
        )}
      </div>

      <Separator />

      <div className="flex w-full">
        <h2 className="text-xl font-bold">Users</h2>
      </div>

      <div className="mt-2">
        {userGroup.users.length > 0 ? (
          <>
            <Table className="overflow-visible">
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead className="flex w-full">
                    <div className="ml-auto">Remove User</div>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {userGroup.users.map((groupMember) => {
                  return (
                    <TableRow key={groupMember.id}>
                      <TableCell className="whitespace-normal break-all">
                        {groupMember.email}
                      </TableCell>
                      <TableCell>
                        <UserRoleDropdown
                          user={groupMember}
                          group={userGroup}
                          onSuccess={onRoleChangeSuccess}
                          onError={onRoleChangeError}
                          isAdmin={isAdmin}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex w-full">
                          <div className="ml-auto m-2">
                            {(isAdmin ||
                              !userGroup.curator_ids.includes(
                                groupMember.id
                              )) && (
                              <DeleteButton
                                onClick={async () => {
                                  const response = await updateUserGroup(
                                    userGroup.id,
                                    {
                                      user_ids: userGroup.users
                                        .filter(
                                          (userGroupUser) =>
                                            userGroupUser.id !== groupMember.id
                                        )
                                        .map(
                                          (userGroupUser) => userGroupUser.id
                                        ),
                                      cc_pair_ids: userGroup.cc_pairs.map(
                                        (ccPair) => ccPair.id
                                      ),
                                    }
                                  );
                                  if (response.ok) {
                                    setPopup({
                                      message:
                                        "Successfully removed user from group",
                                      type: "success",
                                    });
                                  } else {
                                    const responseJson = await response.json();
                                    const errorMsg =
                                      responseJson.detail ||
                                      responseJson.message;
                                    setPopup({
                                      message: `Error removing user from group - ${errorMsg}`,
                                      type: "error",
                                    });
                                  }
                                  refreshUserGroup();
                                }}
                              />
                            )}
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </>
        ) : (
          <div className="text-sm">No users in this group...</div>
        )}
      </div>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="sm"
              className={userGroup.is_up_to_date ? "" : "opacity-50"}
              variant="submit"
              onClick={() => {
                if (userGroup.is_up_to_date) {
                  setAddMemberFormVisible(true);
                }
              }}
            >
              Add Users
            </Button>
          </TooltipTrigger>
          {!userGroup.is_up_to_date && (
            <TooltipContent>
              <p>Cannot update group while sync is occurring</p>
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>
      {addMemberFormVisible && (
        <AddMemberForm
          users={users}
          userGroup={userGroup}
          onClose={() => {
            setAddMemberFormVisible(false);
            refreshUserGroup();
          }}
          setPopup={setPopup}
        />
      )}

      <Separator />

      <h2 className="text-xl font-bold mt-8">Connectors</h2>
      <div className="mt-2">
        {userGroup.cc_pairs.length > 0 ? (
          <>
            <Table className="overflow-visible">
              <TableHeader>
                <TableRow>
                  <TableHead>Connector</TableHead>
                  <TableHead className="flex w-full">
                    <div className="ml-auto">Remove Connector</div>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {userGroup.cc_pairs.map((ccPair) => {
                  return (
                    <TableRow key={ccPair.id}>
                      <TableCell className="whitespace-normal break-all">
                        <ConnectorTitle
                          connector={ccPair.connector}
                          ccPairId={ccPair.id}
                          ccPairName={ccPair.name}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex w-full">
                          <div className="ml-auto m-2">
                            <DeleteButton
                              onClick={async () => {
                                const response = await updateUserGroup(
                                  userGroup.id,
                                  {
                                    user_ids: userGroup.users.map(
                                      (userGroupUser) => userGroupUser.id
                                    ),
                                    cc_pair_ids: userGroup.cc_pairs
                                      .filter(
                                        (userGroupCCPair) =>
                                          userGroupCCPair.id != ccPair.id
                                      )
                                      .map((ccPair) => ccPair.id),
                                  }
                                );
                                if (response.ok) {
                                  setPopup({
                                    message:
                                      "Successfully removed connector from group",
                                    type: "success",
                                  });
                                } else {
                                  const responseJson = await response.json();
                                  const errorMsg =
                                    responseJson.detail || responseJson.message;
                                  setPopup({
                                    message: `Error removing connector from group - ${errorMsg}`,
                                    type: "error",
                                  });
                                }
                                refreshUserGroup();
                              }}
                            />
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </>
        ) : (
          <div className="text-sm">No connectors in this group...</div>
        )}
      </div>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="sm"
              className={userGroup.is_up_to_date ? "" : "opacity-50"}
              variant="submit"
              onClick={() => {
                if (userGroup.is_up_to_date) {
                  setAddConnectorFormVisible(true);
                }
              }}
            >
              Add Connectors
            </Button>
          </TooltipTrigger>
          {!userGroup.is_up_to_date && (
            <TooltipContent>
              <p>Cannot update group while sync is occurring</p>
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>

      {addConnectorFormVisible && (
        <AddConnectorForm
          ccPairs={ccPairs}
          userGroup={userGroup}
          onClose={() => {
            setAddConnectorFormVisible(false);
            refreshUserGroup();
          }}
          setPopup={setPopup}
        />
      )}

      <Separator />

      <h2 className="text-xl font-bold mt-8 mb-2">Document Sets</h2>

      <div>
        {userGroup.document_sets.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {userGroup.document_sets.map((documentSet) => {
              return (
                <Bubble isSelected key={documentSet.id}>
                  <div className="flex">
                    <BookmarkIcon />
                    <Text className="ml-1">{documentSet.name}</Text>
                  </div>
                </Bubble>
              );
            })}
          </div>
        ) : (
          <>
            <Text>No document sets in this group...</Text>
          </>
        )}
      </div>

      <Separator />

      <h2 className="text-xl font-bold mt-8 mb-2">Assistants</h2>

      <div>
        {userGroup.document_sets.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {userGroup.personas.map((persona) => {
              return (
                <Bubble isSelected key={persona.id}>
                  <div className="flex">
                    <RobotIcon />
                    <Text className="ml-1">{persona.name}</Text>
                  </div>
                </Bubble>
              );
            })}
          </div>
        ) : (
          <>
            <Text>No Assistants in this group...</Text>
          </>
        )}
      </div>

      <Separator />

      <h2 className="text-xl font-bold mt-8 mb-2">Token Rate Limits</h2>

      <AddTokenRateLimitForm
        isOpen={addRateLimitFormVisible}
        setIsOpen={setAddRateLimitFormVisible}
        setPopup={setPopup}
        userGroupId={userGroup.id}
      />

      <GenericTokenRateLimitTable
        fetchUrl={`/api/admin/token-rate-limits/user-group/${userGroup.id}`}
        hideHeading
        isAdmin={isAdmin}
      />

      {isAdmin && (
        <Button
          variant="submit"
          size="sm"
          className="mt-3"
          onClick={() => setAddRateLimitFormVisible(true)}
        >
          Create a Token Rate Limit
        </Button>
      )}
    </div>
  );
};
