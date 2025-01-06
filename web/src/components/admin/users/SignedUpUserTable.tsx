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

const ITEMS_PER_PAGE = 10;
const PAGES_PER_BATCH = 2;
import { useUser } from "@/components/user/UserProvider";
import { LeaveOrganizationButton } from "./buttons/LeaveOrganizationButton";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

interface Props {
  invitedUsers: InvitedUserSnapshot[];
  setPopup: (spec: PopupSpec) => void;
  q: string;
  invitedUsersMutate: () => void;
}

const SignedUpUserTable = ({
  invitedUsers,
  setPopup,
  q = "",
  invitedUsersMutate,
}: Props) => {
  const [filters, setFilters] = useState<{
    is_active?: boolean;
    roles?: UserRole[];
  }>({});

  const [selectedRoles, setSelectedRoles] = useState<UserRole[]>([]);

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
          <SelectContent className="bg-neutral-50">
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
          <SelectContent className="bg-neutral-50">
            {Object.entries(USER_ROLE_LABELS)
              .filter(([role]) => role !== UserRole.EXT_PERM_USER)
              .map(([role, label]) => (
                <div
                  key={role}
                  className="flex items-center space-x-2 px-2 py-1.5 cursor-pointer hover:bg-gray-200"
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
            className="border border-neutral-300 bg-neutral p-1 rounded text-sm hover:bg-neutral-200"
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
    return NEXT_PUBLIC_CLOUD_ENABLED && user.id === currentUser?.id ? (
      <LeaveOrganizationButton
        user={user}
        setPopup={setPopup}
        mutate={refresh}
      />
    ) : (
      <>
        <DeactivateUserButton
          user={user}
          deactivate={user.is_active}
          setPopup={setPopup}
          mutate={refresh}
        />
        {!user.is_active && (
          <DeleteUserButton user={user} setPopup={setPopup} mutate={refresh} />
        )}
      </>
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
                  <TableCell className="text-right w-[200px]">
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
    </>
  );
};

export default SignedUpUserTable;
