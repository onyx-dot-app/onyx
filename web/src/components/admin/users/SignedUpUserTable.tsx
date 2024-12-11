import { type User, UserStatus, UserRole } from "@/lib/types";
import CenteredPageSelector from "./CenteredPageSelector";
import { type PageSelectorProps } from "@/components/PageSelector";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { TableHeader } from "@/components/ui/table";
import { UserRoleDropdown } from "./buttons/UserRoleDropdown";
import { DeleteUserButton } from "./buttons/DeleteUserButton";
import { DeactivaterButton } from "./buttons/DeactivaterButton";

interface Props {
  users: Array<User>;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
}

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
          {users
            // Dont want to show external permissioned users because it's scary
            .filter((user) => user.role !== UserRole.EXT_PERM_USER)
            .map((user) => (
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
  );
};

export default SignedUpUserTable;
