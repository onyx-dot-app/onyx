import {
  type User,
  UserStatus,
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
    status?: UserStatus.live | UserStatus.deactivated;
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
          value={filters.status || "all"}
          onValueChange={(selectedStatus) =>
            setFilters((prev) => {
              if (selectedStatus === "all") {
                const { status, ...rest } = prev;
                return rest;
              }
              return {
                ...prev,
                status: selectedStatus as
                  | UserStatus.live
                  | UserStatus.deactivated,
              };
            })
          }
        >
          <SelectTrigger className="w-[260px] h-[34px] bg-neutral">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-neutral-50">
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="live">Active</SelectItem>
            <SelectItem value="deactivated">Inactive</SelectItem>
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
      return <p>Slack User</p>;
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
    return (
      <>
        <DeactivateUserButton
          user={user}
          deactivate={user.status === UserStatus.live}
          setPopup={setPopup}
          mutate={refresh}
        />
        {user.status === UserStatus.deactivated && (
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
                    {filters.roles?.length || filters.status
                      ? "No users found matching your filters"
                      : `No users found matching "${q}"`}
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              pageOfUsers
                ?.filter((user) => user.role !== UserRole.EXT_PERM_USER)
                .map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>{user.email}</TableCell>
                    <TableCell className="w-40">
                      {renderUserRoleDropdown(user)}
                    </TableCell>
                    <TableCell className="text-center">
                      <i>{user.status === "live" ? "Active" : "Inactive"}</i>
                    </TableCell>
                    <TableCell className="flex justify-end">
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
