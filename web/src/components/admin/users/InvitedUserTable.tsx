import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import CenteredPageSelector from "./CenteredPageSelector";
import { type PageSelectorProps } from "@/components/PageSelector";

import { type User } from "@/lib/types";
import useSWRMutation from "swr/mutation";
import { TableHeader } from "@/components/ui/table";

interface Props {
  users: Array<User>;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
}

const RemoveUserButton = ({
  user,
  onSuccess,
  onError,
}: {
  user: User;
  onSuccess: () => void;
  onError: (message: string) => void;
}) => {
  const { trigger } = useSWRMutation(
    "/api/manage/admin/remove-invited-user",
    userMutationFetcher,
    { onSuccess, onError }
  );
  return (
    <Button onClick={() => trigger({ user_email: user.email })}>
      Uninvite User
    </Button>
  );
};

const InvitedUserTable = ({
  users,
  setPopup,
  currentPage,
  totalPages,
  onPageChange,
  mutate,
}: Props & PageSelectorProps) => {
  if (!users.length) return null;

  const onRemovalSuccess = () => {
    mutate();
    setPopup({
      message: "User uninvited!",
      type: "success",
    });
  };
  const onRemovalError = (errorMsg: string) => {
    setPopup({
      message: `Unable to uninvite user - ${errorMsg}`,
      type: "error",
    });
  };

  return (
    <>
      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>
              <div className="flex justify-end">Actions</div>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map((user) => (
            <TableRow key={user.email}>
              <TableCell>{user.email}</TableCell>
              <TableCell>
                <div className="flex justify-end">
                  <RemoveUserButton
                    user={user}
                    onSuccess={onRemovalSuccess}
                    onError={onRemovalError}
                  />
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {totalPages > 1 ? (
        <CenteredPageSelector
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={onPageChange}
        />
      ) : null}
    </>
  );
};

export default InvitedUserTable;
