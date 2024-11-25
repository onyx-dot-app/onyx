import { type User, UserStatus, UserRole, USER_ROLE_LABELS } from "@/lib/types";
import CenteredPageSelector from "./CenteredPageSelector";
import { type PageSelectorProps } from "@/components/PageSelector";
import { HidableSection } from "@/app/admin/assistants/HidableSection";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { GenericConfirmModal } from "@/components/modals/GenericConfirmModal";
import { useState } from "react";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { DeleteEntityModal } from "@/components/modals/DeleteEntityModal";
import { TableHeader } from "@/components/ui/table";

interface Props {
  users: Array<User>;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
}

const UserRoleDropdown = ({
  user,
  onSuccess,
  onError,
}: {
  user: User;
  onSuccess: () => void;
  onError: (message: string) => void;
}) => {
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [pendingRole, setPendingRole] = useState<string | null>(null);

  const { trigger: setUserRole, isMutating: isSettingRole } = useSWRMutation(
    "/api/manage/set-user-role",
    userMutationFetcher,
    { onSuccess, onError }
  );
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const handleChange = (value: string) => {
    if (value === user.role) return;
    if (user.role === UserRole.CURATOR) {
      setShowConfirmModal(true);
      setPendingRole(value);
    } else {
      setUserRole({
        user_email: user.email,
        new_role: value,
      });
    }
  };

  const handleConfirm = () => {
    if (pendingRole) {
      setUserRole({
        user_email: user.email,
        new_role: pendingRole,
      });
    }
    setShowConfirmModal(false);
    setPendingRole(null);
  };

  return (
    <>
      <Select
        value={user.role}
        onValueChange={handleChange}
        disabled={isSettingRole}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(USER_ROLE_LABELS).map(([role, label]) =>
            !isPaidEnterpriseFeaturesEnabled &&
            (role === UserRole.CURATOR ||
              role === UserRole.GLOBAL_CURATOR) ? null : (
              <SelectItem
                key={role}
                value={role}
                className={
                  role === UserRole.CURATOR
                    ? "opacity-30 cursor-not-allowed"
                    : ""
                }
                title={
                  role === UserRole.CURATOR
                    ? "Curator role must be assigned in the Groups tab"
                    : ""
                }
              >
                {label}
              </SelectItem>
            )
          )}
        </SelectContent>
      </Select>
      {showConfirmModal && (
        <GenericConfirmModal
          title="Change Curator Role"
          message={`Warning: Switching roles from Curator to ${
            USER_ROLE_LABELS[pendingRole as UserRole] ??
            USER_ROLE_LABELS[user.role]
          } will remove their status as individual curators from all groups.`}
          confirmText={`Switch Role to ${
            USER_ROLE_LABELS[pendingRole as UserRole] ??
            USER_ROLE_LABELS[user.role]
          }`}
          onClose={() => setShowConfirmModal(false)}
          onConfirm={handleConfirm}
        />
      )}
    </>
  );
};

const DeactivaterButton = ({
  user,
  deactivate,
  setPopup,
  mutate,
}: {
  user: User;
  deactivate: boolean;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
}) => {
  const { trigger, isMutating } = useSWRMutation(
    deactivate
      ? "/api/manage/admin/deactivate-user"
      : "/api/manage/admin/activate-user",
    userMutationFetcher,
    {
      onSuccess: () => {
        mutate();
        setPopup({
          message: `User ${deactivate ? "deactivated" : "activated"}!`,
          type: "success",
        });
      },
      onError: (errorMsg) =>
        setPopup({ message: errorMsg.message, type: "error" }),
    }
  );
  return (
    <Button
      className="w-min"
      onClick={() => trigger({ user_email: user.email })}
      disabled={isMutating}
      size="sm"
    >
      {deactivate ? "Deactivate" : "Activate"}
    </Button>
  );
};

const DeleteUserButton = ({
  user,
  setPopup,
  mutate,
}: {
  user: User;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
}) => {
  const { trigger, isMutating } = useSWRMutation(
    "/api/manage/admin/delete-user",
    userMutationFetcher,
    {
      onSuccess: () => {
        mutate();
        setPopup({
          message: "User deleted successfully!",
          type: "success",
        });
      },
      onError: (errorMsg) =>
        setPopup({
          message: `Unable to delete user - ${errorMsg}`,
          type: "error",
        }),
    }
  );

  const [showDeleteModal, setShowDeleteModal] = useState(false);
  return (
    <>
      {showDeleteModal && (
        <DeleteEntityModal
          entityType="user"
          entityName={user.email}
          onClose={() => setShowDeleteModal(false)}
          onSubmit={() => trigger({ user_email: user.email, method: "DELETE" })}
          additionalDetails="All data associated with this user will be deleted (including personas, tools and chat sessions)."
        />
      )}

      <Button
        className="w-min"
        onClick={() => setShowDeleteModal(true)}
        disabled={isMutating}
        size="sm"
        variant="destructive"
      >
        Delete
      </Button>
    </>
  );
};

const SignedUpUserTable = ({
  users,
  setPopup,
  currentPage,
  totalPages,
  onPageChange,
  mutate,
}: Props & PageSelectorProps) => {
  if (!users.length) return null;

  const handlePopup = (message: string, type: "success" | "error") => {
    if (type === "success") mutate();
    setPopup({ message, type });
  };

  const onRoleChangeSuccess = () =>
    handlePopup("User role updated successfully!", "success");
  const onRoleChangeError = (errorMsg: string) =>
    handlePopup(`Unable to update user role - ${errorMsg}`, "error");

  return (
    <HidableSection sectionTitle="Current Users">
      <>
        {totalPages > 1 ? (
          <CenteredPageSelector
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={onPageChange}
          />
        ) : null}
        <Table className="overflow-visible">
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead className="text-center">Role</TableHead>
              <TableHead className="text-center">Status</TableHead>
              <TableHead>
                <div className="flex">
                  <div className="ml-auto">Actions</div>
                </div>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => (
              <TableRow key={user.id}>
                <TableCell>{user.email}</TableCell>
                <TableCell className="w-40 ">
                  <UserRoleDropdown
                    user={user}
                    onSuccess={onRoleChangeSuccess}
                    onError={onRoleChangeError}
                  />
                </TableCell>
                <TableCell className="text-center">
                  <i>{user.status === "live" ? "Active" : "Inactive"}</i>
                </TableCell>
                <TableCell>
                  <div className="flex justify-end  gap-x-2">
                    <DeactivaterButton
                      user={user}
                      deactivate={user.status === UserStatus.live}
                      setPopup={setPopup}
                      mutate={mutate}
                    />
                    {user.status == UserStatus.deactivated && (
                      <DeleteUserButton
                        user={user}
                        setPopup={setPopup}
                        mutate={mutate}
                      />
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </>
    </HidableSection>
  );
};

export default SignedUpUserTable;
