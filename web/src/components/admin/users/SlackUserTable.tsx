import React from "react";
import { User } from "@/lib/types";
import {
  Table,
  TableCell,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PopupSpec } from "../connectors/Popup";
import { InviteUserButton } from "./buttons/InviteUserButton";
import { PageSelectorProps } from "@/components/PageSelector";
import CenteredPageSelector from "./CenteredPageSelector";

interface SlackUserTableProps {
  invitedUsers: User[];
  slackusers: User[];
  mutate: () => void;
  setPopup: (spec: PopupSpec) => void;
}

const SlackUserTable: React.FC<SlackUserTableProps & PageSelectorProps> = ({
  invitedUsers,
  slackusers,
  mutate,
  currentPage,
  totalPages,
  onPageChange,
  setPopup,
}) => {
  return (
    <>
      {totalPages > 1 ? (
        <CenteredPageSelector
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={onPageChange}
        />
      ) : null}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead className="text-center">Status</TableHead>
            <TableHead>
              <div className="flex">
                <div className="ml-auto">Actions</div>
              </div>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {slackusers.map((user) => (
            <TableRow key={user.id}>
              <TableCell>{user.email}</TableCell>
              <TableCell className="text-center">
                <i>{user.status === "live" ? "Active" : "Inactive"}</i>
              </TableCell>
              <TableCell className="flex justify-end">
                <InviteUserButton
                  user={user}
                  invited={invitedUsers
                    .map((u) => u.email)
                    .includes(user.email)}
                  setPopup={setPopup}
                  mutate={mutate}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
};

export default SlackUserTable;
