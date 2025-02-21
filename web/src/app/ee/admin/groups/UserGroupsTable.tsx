"use client";

import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { LoadingAnimation } from "@/components/Loading";
import { BasicTable } from "@/components/admin/connectors/BasicTable";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { TrashIcon } from "@/components/icons/icons";
import { deleteUserGroup } from "./lib";
import { useRouter } from "next/navigation";
import { FiEdit2, FiUser } from "react-icons/fi";
import { User, UserGroup } from "@/lib/types";
import Link from "next/link";
import { DeleteButton } from "@/components/DeleteButton";
import { TableHeader } from "@/components/ui/table";

const MAX_USERS_TO_DISPLAY = 6;

const SimpleUserDisplay = ({ user }: { user: User }) => {
  return (
    <div className="flex my-0.5">
      <FiUser className="mr-2 my-auto" /> {user.email}
    </div>
  );
};

interface UserGroupsTableProps {
  userGroups: UserGroup[];
  setPopup: (popupSpec: PopupSpec | null) => void;
  refresh: () => void;
}

export const UserGroupsTable = ({
  userGroups,
  setPopup,
  refresh,
}: UserGroupsTableProps) => {
  const router = useRouter();

  // sort by name for consistent ordering
  userGroups.sort((a, b) => {
    if (a.name < b.name) {
      return -1;
    } else if (a.name > b.name) {
      return 1;
    } else {
      return 0;
    }
  });

  return (
    <div>
      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Connectors</TableHead>
            <TableHead>Users</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Delete</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {userGroups
            .filter((userGroup) => !userGroup.is_up_for_deletion)
            .map((userGroup) => {
              return (
                <TableRow key={userGroup.id}>
                  <TableCell>
                    <Link
                      className="whitespace-nowrap overflow-hidden text-ellipsis inline-flex items-center cursor-pointer p-2 rounded hover:bg-accent-background-hovered max-w-full"
                      href={`/admin/groups/${userGroup.id}`}
                    >
                      <FiEdit2 className="mr-2 flex-shrink-0" />
                      <span className="font-medium truncate">
                        {userGroup.name}
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell>
                    {userGroup.cc_pairs.length > 0 ? (
                      <div>
                        {userGroup.cc_pairs.map((ccPairDescriptor, ind) => {
                          return (
                            <div
                              className={
                                ind !== userGroup.cc_pairs.length - 1
                                  ? "mb-3"
                                  : ""
                              }
                              key={ccPairDescriptor.id}
                            >
                              <ConnectorTitle
                                connector={ccPairDescriptor.connector}
                                ccPairId={ccPairDescriptor.id}
                                ccPairName={ccPairDescriptor.name}
                                showMetadata={false}
                              />
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      "-"
                    )}
                  </TableCell>
                  <TableCell>
                    {userGroup.users.length > 0 ? (
                      <div>
                        {userGroup.users.length <= MAX_USERS_TO_DISPLAY ? (
                          userGroup.users.map((user) => {
                            return (
                              <SimpleUserDisplay key={user.id} user={user} />
                            );
                          })
                        ) : (
                          <div>
                            {userGroup.users
                              .slice(0, MAX_USERS_TO_DISPLAY)
                              .map((user) => {
                                return (
                                  <SimpleUserDisplay
                                    key={user.id}
                                    user={user}
                                  />
                                );
                              })}
                            <div>
                              + {userGroup.users.length - MAX_USERS_TO_DISPLAY}{" "}
                              more
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      "-"
                    )}
                  </TableCell>
                  <TableCell>
                    {userGroup.is_up_to_date ? (
                      <div className="text-success">Up to date!</div>
                    ) : (
                      <div className="w-10">
                        <LoadingAnimation text="Syncing" />
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <DeleteButton
                      onClick={async (event) => {
                        event.stopPropagation();
                        const response = await deleteUserGroup(userGroup.id);
                        if (response.ok) {
                          setPopup({
                            message: `User Group "${userGroup.name}" deleted`,
                            type: "success",
                          });
                        } else {
                          const errorMsg = (await response.json()).detail;
                          setPopup({
                            message: `Failed to delete User Group - ${errorMsg}`,
                            type: "error",
                          });
                        }
                        refresh();
                      }}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>
    </div>
  );

  return (
    <div>
      <BasicTable
        columns={[
          {
            header: "Name",
            key: "name",
          },
          {
            header: "Connectors",
            key: "ccPairs",
          },
          {
            header: "Users",
            key: "users",
          },
          {
            header: "Status",
            key: "status",
          },
          {
            header: "Delete",
            key: "delete",
          },
        ]}
        data={userGroups
          .filter((userGroup) => !userGroup.is_up_for_deletion)
          .map((userGroup) => {
            return {
              id: userGroup.id,
              name: userGroup.name,
              ccPairs: (
                <div>
                  {userGroup.cc_pairs.map((ccPairDescriptor, ind) => {
                    return (
                      <div
                        className={
                          ind !== userGroup.cc_pairs.length - 1 ? "mb-3" : ""
                        }
                        key={ccPairDescriptor.id}
                      >
                        <ConnectorTitle
                          connector={ccPairDescriptor.connector}
                          ccPairId={ccPairDescriptor.id}
                          ccPairName={ccPairDescriptor.name}
                          showMetadata={false}
                        />
                      </div>
                    );
                  })}
                </div>
              ),
              users: (
                <div>
                  {userGroup.users.length <= MAX_USERS_TO_DISPLAY ? (
                    userGroup.users.map((user) => {
                      return <SimpleUserDisplay key={user.id} user={user} />;
                    })
                  ) : (
                    <div>
                      {userGroup.users
                        .slice(0, MAX_USERS_TO_DISPLAY)
                        .map((user) => {
                          return (
                            <SimpleUserDisplay key={user.id} user={user} />
                          );
                        })}
                      <div className="text-text-300">
                        + {userGroup.users.length - MAX_USERS_TO_DISPLAY} more
                      </div>
                    </div>
                  )}
                </div>
              ),
              status: userGroup.is_up_to_date ? (
                <div className="text-emerald-600">Up to date!</div>
              ) : (
                <div className="text-text-300 w-10">
                  <LoadingAnimation text="Syncing" />
                </div>
              ),
              delete: (
                <div
                  className="cursor-pointer"
                  onClick={async (event) => {
                    event.stopPropagation();
                    const response = await deleteUserGroup(userGroup.id);
                    if (response.ok) {
                      setPopup({
                        message: `User Group "${userGroup.name}" deleted`,
                        type: "success",
                      });
                    } else {
                      const errorMsg = (await response.json()).detail;
                      setPopup({
                        message: `Failed to delete User Group - ${errorMsg}`,
                        type: "error",
                      });
                    }
                    refresh();
                  }}
                >
                  <TrashIcon />
                </div>
              ),
            };
          })}
        onSelect={(data) => {
          router.push(`/admin/groups/${data.id}`);
        }}
      />
    </div>
  );
};
