import React from "react";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import {
  type User,
  UserRole,
  InvitedUserSnapshot,
  USER_ROLE_LABELS,
} from "@/lib/types";
import { useState } from "react";
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
import { RefreshCcw } from "lucide-react";
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
}: Props) => {
  const { t } = useTranslation();
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
  } = usePaginatedFetch<User>({
    itemsPerPage: ITEMS_PER_PAGE,
    pagesPerBatch: PAGES_PER_BATCH,
    endpoint: "/api/manage/users/accepted",
    query: q,
    filter: filters,
  });

  const { user: currentUser } = useUser();

  if (error) {
    return (
      <ErrorCallout
        errorTitle={t(k.LOAD_USERS_ERROR)}
        errorMsg={error?.message}
      />
    );
  }

  const handlePopup = (message: string, type: "success" | "error") => {
    if (type === "success") refresh();
    setPopup({ message, type });
  };

  const onRoleChangeSuccess = () =>
    handlePopup(t(k.USER_ROLE_UPDATED_SUCCESS), "success");
  const onRoleChangeError = (errorMsg: string) =>
    handlePopup(`${t(k.USER_ROLE_UPDATE_FAILED)} ${errorMsg}`, "error");

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
      <div className="flex items-center gap-4 py-4">
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
          <SelectContent className="bg-background-50">
            <SelectItem value="all">{t(k.ALL_STATUS)}</SelectItem>
            <SelectItem value="true">{t(k.ACTIVE)}</SelectItem>
            <SelectItem value="false">{t(k.INACTIVE)}</SelectItem>
          </SelectContent>
        </Select>
        <Select value="roles">
          <SelectTrigger className="w-[260px] h-[34px] bg-neutral">
            <SelectValue>
              {filters.roles?.length
                ? `${filters.roles.length} ${t(k.ROLE_S_SELECTED)}`
                : t(k.ALL_ROLES)}
            </SelectValue>
          </SelectTrigger>
          <SelectContent className="bg-background-50">
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
                    checked={filters.roles?.includes(role as UserRole) || false}
                    onChange={(e) => e.stopPropagation()}
                  />

                  <label className="text-sm font-normal">{label}</label>
                </div>
              ))}
          </SelectContent>
        </Select>
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
            <span className="ml-3">{t(k._36)}</span>
          </button>
        ))}
      </div>
    </>
  );

  const renderUserRoleDropdown = (user: User) => {
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
            <span className="sr-only">{t(k.OPEN_MENU)}</span>
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-56">
          <div className="grid gap-2">
            {NEXT_PUBLIC_CLOUD_ENABLED && user.id === currentUser?.id ? (
              <LeaveOrganizationButton
                user={user}
                setPopup={setPopup}
                mutate={refresh}
                className={buttonClassName}
              >
                <LogOut className="mr-2 h-4 w-4 flex-shrink-0" />
                <span className="truncate">{t(k.LEAVE_ORGANIZATION)}</span>
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
                    <UserMinus className="mr-2 h-4 w-4 flex-shrink-0" />
                    <span className="truncate">{t(k.DELETE_USER)}</span>
                  </DeleteUserButton>
                )}
                <DeactivateUserButton
                  user={user}
                  deactivate={user.is_active}
                  setPopup={setPopup}
                  mutate={refresh}
                  className={buttonClassName}
                >
                  <UserX className="mr-2 h-4 w-4 flex-shrink-0" />
                  <span className="truncate">
                    {user.is_active ? t(k.DEACTIVATE_USER) : t(k.ACTIVATE_USER)}
                  </span>
                </DeactivateUserButton>
              </>
            )}
            {user.password_configured && (
              <Button
                variant="ghost"
                className={buttonClassName}
                onClick={() => handleResetPassword(user)}
              >
                <KeyRound className="mr-2 h-4 w-4 flex-shrink-0" />
                <span className="truncate">{t(k.RESET_PASSWORD)}</span>
              </Button>
            )}
          </div>
        </PopoverContent>
      </Popover>
    );
  };

  const renderActionButtons = (user: User) => {
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
            <TableHead>{t(k.EMAIL)}</TableHead>
            <TableHead className="text-center">{t(k.ROLE)}</TableHead>
            <TableHead className="text-center">{t(k.STATUS)}</TableHead>
            <TableHead>
              <div className="flex">
                <div className="ml-auto">{t(k.ACTIONS)}</div>
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
                      ? t(k.NO_USERS_FOUND_MATCHING_YOUR_F)
                      : `${t(k.NO_USERS_FOUND_MATCHING)}${q}${t(k._17)}`}
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
                    <i>{user.is_active ? t(k.ACTIVE) : t(k.INACTIVE)}</i>
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
