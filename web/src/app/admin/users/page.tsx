"use client";

import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  Button,
} from "@tremor/react";
import { LoadingAnimation } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { usePopup } from "@/components/admin/connectors/Popup";
import { UsersIcon } from "@/components/icons/icons";
import { fetcher } from "@/lib/fetcher";
import { User } from "@/lib/types";
import useSWR, { mutate } from "swr";

const UsersTable = () => {
  const { popup, setPopup } = usePopup();

  const {
    data: users,
    isLoading,
    error,
  } = useSWR<User[]>("/api/manage/users", fetcher);

  if (isLoading) {
    return <LoadingAnimation text="Loading" />;
  }

  if (error || !users) {
    return <div className="text-error">Error loading users</div>;
  }

  return (
    <div>
      {popup}

      <Table className="overflow-visible">
        <TableHead>
          <TableRow>
            <TableHeaderCell>Email</TableHeaderCell>
            <TableHeaderCell>Role</TableHeaderCell>
            <TableHeaderCell>
              <div className="flex">
                <div className="ml-auto">Actions</div>
              </div>
            </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {users.map((user) => (
            <TableRow key={user.id}>
              <TableCell>{user.email}</TableCell>
              <TableCell>
                <i>{user.role === "admin" ? "Admin" : "User"}</i>
              </TableCell>
              <TableCell>
                <div className="flex justify-end space-x-2">
                  {user.role !== "admin" && (
                    <Button
                      onClick={async () => {
                        const res = await fetch(
                          "/api/manage/promote-user-to-admin",
                          {
                            method: "PATCH",
                            headers: {
                              "Content-Type": "application/json",
                            },
                            body: JSON.stringify({
                              user_email: user.email,
                            }),
                          }
                        );
                        if (!res.ok) {
                          const errorMsg = await res.text();
                          setPopup({
                            message: `Unable to promote user - ${errorMsg}`,
                            type: "error",
                          });
                        } else {
                          mutate("/api/manage/users");
                          setPopup({
                            message: "User promoted to admin user!",
                            type: "success",
                          });
                        }
                      }}
                    >
                      Promote to Admin User
                    </Button>
                  )}
                  {user.role === "admin" && (
                    <Button
                      onClick={async () => {
                        const res = await fetch(
                          "/api/manage/demote-admin-to-basic",
                          {
                            method: "PATCH",
                            headers: {
                              "Content-Type": "application/json",
                            },
                            body: JSON.stringify({
                              user_email: user.email,
                            }),
                          }
                        );
                        if (!res.ok) {
                          const errorMsg = await res.text();
                          setPopup({
                            message: `Unable to demote admin - ${errorMsg}`,
                            type: "error",
                          });
                        } else {
                          mutate("/api/manage/users");
                          setPopup({
                            message: "Admin demoted to basic user!",
                            type: "success",
                          });
                        }
                      }}
                    >
                      Demote to Basic User
                    </Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

const Page = () => {
  return (
    <div className="mx-auto container">
      <AdminPageTitle title="Manage Users" icon={<UsersIcon size={32} />} />

      <UsersTable />
    </div>
  );
};

export default Page;
