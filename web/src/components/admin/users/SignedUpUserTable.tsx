import {
  type User,
  UserRole,
  InvitedUserSnapshot,
  USER_ROLE_LABELS,
} from "@/lib/types";
import { ReactNode, useEffect, useState } from "react";
import CenteredPageSelector from "./CenteredPageSelector";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { TableHeader } from "@/components/ui/table";
import UserRoleDropdown from "./buttons/UserRoleDropdown";
import DeleteUserButton from "./buttons/DeleteUserButton";
import DeactivateUserButton from "./buttons/DeactivateUserButton";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { InviteUserButton } from "./buttons/InviteUserButton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { useUser } from "@/components/user/UserProvider";
import { LeaveOrganizationButton } from "./buttons/LeaveOrganizationButton";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import ResetPasswordModal from "./ResetPasswordModal";
import {
  MoreHorizontal,
  LogOut,
  UserMinus,
  UserX,
  KeyRound,
} from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

const ITEMS_PER_PAGE = 10;
const PAGES_PER_BATCH = 2;

interface Props {
  invitedUsers: InvitedUserSnapshot[];
  setPopup: (spec: PopupSpec) => void;
  q: string;
  invitedUsersMutate: () => void;
  countDisplay?: ReactNode;
  onTotalItemsChange?: (count: number) => void;
  onLoadingChange?: (isLoading: boolean) => void;
}

interface ActionMenuProps {
  user: User;
  currentUser: User | null;
  setPopup: (spec: PopupSpec) => void;
  refresh: () => void;
  invitedUsersMutate: () => void;
  handleResetPassword: (user: User) => void;
}

const SignedUpUserTable = ({
  invitedUsers,
  setPopup,
  q = "",
  invitedUsersMutate,
  countDisplay,
  onTotalItemsChange,
  onLoadingChange,
}: Props) => {
  const [filters, setFilters] = useState<{
    is_active?: boolean;
    roles?: UserRole[];
  }>({});

  const [selectedRoles, setSelectedRoles] = useState<UserRole[]>([]);
  const [resetPasswordUser, setResetPasswordUser] = useState<User | null>(null);

  const {
    currentPageData: pageOfUsers,
    isLoading,
    error,
    currentPage,
    totalPages,
    goToPage,
    refresh,
    totalItems,
  } = usePaginatedFetch<User>({
    itemsPerPage: ITEMS_PER_PAGE,
    pagesPerBatch: PAGES_PER_BATCH,
    endpoint: "/api/manage/users/accepted",
    query: q,
    filter: filters,
  });

  const { user: currentUser } = useUser();

  useEffect(() => {
    onLoadingChange?.(isLoading);
  }, [isLoading, onLoadingChange]);

  useEffect(() => {
    if (pageOfUsers !== null) {
      onTotalItemsChange?.(totalItems);
    }
  }, [pageOfUsers, totalItems, onTotalItemsChange]);

  if (error) {
    return (
      <ErrorCallout
        errorTitle="Error loading users"
        errorMsg={error?.message}
      />
    );
  }

  const handlePopup = (message: string, type: "success" | "error") => {
    if (type === "success") refresh();
    setPopup({ message, type });
  };

  const onRoleChangeSuccess = () =>
    handlePopup("User role updated successfully!", "success");
  const onRoleChangeError = (errorMsg: string) =>
    handlePopup(`Unable to update user role - ${errorMsg}`, "error");

  const toggleRole = (roleEnum: UserRole) => {
    setFilters((prev) => {
      const currentRoles = prev.roles || [];
      const newRoles = currentRoles.includes(roleEnum)
        ? currentRoles.filter((r) => r !== roleEnum) // Remove role if already selected
        : [...currentRoles, roleEnum]; // Add role if not selected

      setSelectedRoles(newRoles); // Update selected roles state
      return {
        ...prev,
        roles: newRoles,
      };
    });
  };

  const removeRole = (roleEnum: UserRole) => {
    setSelectedRoles((prev) => prev.filter((role) => role !== roleEnum)); // Remove role from selected roles
    toggleRole(roleEnum); // Deselect the role in filters
  };

  const handleResetPassword = (user: User) => {
    setResetPasswordUser(user);
  };

  // --------------
  // Render Functions
  // --------------

  const renderFilters = () => (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4 py-4">
        <div className="flex flex-wrap items-center gap-4">
          <Select
            value={filters.is_active?.toString() || "all"}
            onValueChange={(selectedStatus) =>
              setFilters((prev) => {
                if (selectedStatus === "all") {
                  const { is_active, ...rest } = prev;
                  return rest;
                }
                return {
                  ...prev,
                  is_active: selectedStatus === "true",
                };
              })
            }
          >
            <SelectTrigger className="w-[260px] h-[34px] bg-neutral">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-background-tint-00">
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="true">Active</SelectItem>
              <SelectItem value="false">Inactive</SelectItem>
            </SelectContent>
          </Select>
          <Select value="roles">
            <SelectTrigger className="w-[260px] h-[34px] bg-neutral">
              <SelectValue>
                {filters.roles?.length
                  ? `${filters.roles.length} role(s) selected`
                  : "All Roles"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="bg-background-tint-00">
              {Object.entries(USER_ROLE_LABELS)
                .filter(([role]) => role !== UserRole.EXT_PERM_USER)
                .map(([role, label]) => (
                  <div
                    key={role}
                    className="flex items-center space-x-2 px-2 py-1.5 cursor-pointer hover:bg-background-200"
                    onClick={() => toggleRole(role as UserRole)}
                  >
                    <input
                      type="checkbox"
                      checked={
                        filters.roles?.includes(role as UserRole) || false
                      }
                      onChange={(e) => e.stopPropagation()}
                    />
                    <label className="text-sm font-normal">{label}</label>
                  </div>
                ))}
            </SelectContent>
          </Select>
        </div>
        {countDisplay}
      </div>
      <div className="flex gap-2 py-1">
        {selectedRoles.map((role) => (
          <button
            key={role}
            className="border border-background-300 bg-neutral p-1 rounded text-sm hover:bg-background-200"
            onClick={() => removeRole(role)}
            style={{ padding: "2px 8px" }}
          >
            <span>{USER_ROLE_LABELS[role]}</span>
            <span className="ml-3">&times;</span>
          </button>
        ))}
      </div>
    </>
  );

  const renderUserRoleDropdown = (user: User) => {
    if (user.role === UserRole.SLACK_USER) {
      return <p className="ml-2">Slack User</p>;
    }
    return (
      <UserRoleDropdown
        user={user}
        onSuccess={onRoleChangeSuccess}
        onError={onRoleChangeError}
      />
    );
  };

  const ActionMenu: React.FC<ActionMenuProps> = ({
    user,
    currentUser,
    setPopup,
    refresh,
    invitedUsersMutate,
    handleResetPassword,
  }) => {
    const buttonClassName = "w-full justify-start";

    return (
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="ghost" className="h-8 w-8 p-0">
            <span className="sr-only">Open menu</span>
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-48">
          <div className="grid gap-2">
            {NEXT_PUBLIC_CLOUD_ENABLED && user.id === currentUser?.id ? (
              <LeaveOrganizationButton
                user={user}
                setPopup={setPopup}
                mutate={refresh}
                className={buttonClassName}
              >
                <LogOut className="mr-2 h-4 w-4" />
                <span>Leave Organization</span>
              </LeaveOrganizationButton>
            ) : (
              <>
                {!user.is_active && (
                  <DeleteUserButton
                    user={user}
                    setPopup={setPopup}
                    mutate={refresh}
                    className={buttonClassName}
                  >
                    <UserMinus className="mr-2 h-4 w-4" />
                    <span>Delete User</span>
                  </DeleteUserButton>
                )}
                <DeactivateUserButton
                  user={user}
                  deactivate={user.is_active}
                  setPopup={setPopup}
                  mutate={refresh}
                  className={buttonClassName}
                >
                  <UserX className="mr-2 h-4 w-4" />
                  <span>{user.is_active ? "Deactivate" : "Activate"} User</span>
                </DeactivateUserButton>
              </>
            )}
            {user.password_configured && (
              <Button
                variant="ghost"
                className={buttonClassName}
                onClick={() => handleResetPassword(user)}
              >
                <KeyRound className="mr-2 h-4 w-4" />
                <span>Reset Password</span>
              </Button>
            )}
          </div>
        </PopoverContent>
      </Popover>
    );
  };

  const renderActionButtons = (user: User) => {
    if (user.role === UserRole.SLACK_USER) {
      return (
        <InviteUserButton
          user={user}
          invited={invitedUsers.map((u) => u.email).includes(user.email)}
          setPopup={setPopup}
          mutate={[refresh, invitedUsersMutate]}
        />
      );
    }
    return (
      <ActionMenu
        user={user}
        currentUser={currentUser}
        setPopup={setPopup}
        refresh={refresh}
        invitedUsersMutate={invitedUsersMutate}
        handleResetPassword={handleResetPassword}
      />
    );
  };

  return (
    <>
      {renderFilters()}
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
        {isLoading ? (
          <TableBody>
            <TableRow>
              <TableCell colSpan={4} className="text-center">
                <ThreeDotsLoader />
              </TableCell>
            </TableRow>
          </TableBody>
        ) : (
          <TableBody>
            {!pageOfUsers?.length ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center">
                  <p className="pt-4 pb-4">
                    {filters.roles?.length || filters.is_active !== undefined
                      ? "No users found matching your filters"
                      : `No users found matching "${q}"`}
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              pageOfUsers.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>{user.email}</TableCell>
                  <TableCell className="w-[180px]">
                    {renderUserRoleDropdown(user)}
                  </TableCell>
                  <TableCell className="text-center w-[140px]">
                    <i>{user.is_active ? "Active" : "Inactive"}</i>
                  </TableCell>
                  <TableCell className="text-right  w-[300px] ">
                    {renderActionButtons(user)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        )}
      </Table>
      {totalPages > 1 && (
        <CenteredPageSelector
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={goToPage}
        />
      )}
      {resetPasswordUser && (
        <ResetPasswordModal
          user={resetPasswordUser}
          onClose={() => setResetPasswordUser(null)}
          setPopup={setPopup}
        />
      )}
    </>
  );
};

export default SignedUpUserTable;
