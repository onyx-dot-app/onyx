import { useState } from "react";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import CenteredPageSelector from "./CenteredPageSelector";
import { ThreeDotsLoader } from "@/components/Loading";
import { InvitedUserSnapshot } from "@/lib/types";
import { TableHeader } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ErrorCallout";
import { FetchError } from "@/lib/fetcher";
import { CheckIcon } from "lucide-react";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";

const USERS_PER_PAGE = 10;

interface Props {
  users: InvitedUserSnapshot[];
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
  error: FetchError | null;
  isLoading: boolean;
  q: string;
}

const PendingUsersTable = ({
  users,
  setPopup,
  mutate,
  error,
  isLoading,
  q,
}: Props) => {
  const [currentPageNum, setCurrentPageNum] = useState<number>(1);
  const [userToApprove, setUserToApprove] = useState<string | null>(null);

  if (!users.length)
    return <p>Users that have requested to join will show up here</p>;

  const totalPages = Math.ceil(users.length / USERS_PER_PAGE);

  // Filter users based on the search query
  const filteredUsers = q
    ? users.filter((user) => user.email.includes(q))
    : users;

  // Get the current page of users
  const currentPageOfUsers = filteredUsers.slice(
    (currentPageNum - 1) * USERS_PER_PAGE,
    currentPageNum * USERS_PER_PAGE
  );

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (error) {
    return (
      <ErrorCallout
        errorTitle="Error loading pending users"
        errorMsg={error?.info?.detail}
      />
    );
  }

  const handleAcceptRequest = async (email: string) => {
    try {
      await fetch("/api/tenants/users/invite/approve", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email }),
      });
      mutate();
      setUserToApprove(null);
    } catch (error) {
      setPopup({
        type: "error",
        message: "Failed to approve user request",
      });
    }
  };

  return (
    <>
      {userToApprove && (
        <ConfirmEntityModal
          entityType="Join Request"
          entityName={userToApprove}
          onClose={() => setUserToApprove(null)}
          onSubmit={() => handleAcceptRequest(userToApprove)}
          actionButtonText="Approve"
          action="approve the join request of"
          additionalDetails={`${userToApprove} has requested to join the team. Approving will add them as a user in this team.`}
          removeConfirmationText
        />
      )}
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
          {currentPageOfUsers.length ? (
            currentPageOfUsers.map((user) => (
              <TableRow key={user.email}>
                <TableCell>{user.email}</TableCell>
                <TableCell>
                  <div className="flex justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setUserToApprove(user.email)}
                    >
                      <CheckIcon className="h-4 w-4" />
                      Accept Join Request
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={2} className="h-24 text-center">
                {`No pending users found matching "${q}"`}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {totalPages > 1 ? (
        <CenteredPageSelector
          currentPage={currentPageNum}
          totalPages={totalPages}
          onPageChange={setCurrentPageNum}
        />
      ) : null}
    </>
  );
};

export default PendingUsersTable;
