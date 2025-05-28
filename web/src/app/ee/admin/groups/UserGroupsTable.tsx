"use client";
import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";

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
            <TableHead>{i18n.t(k.NAME)}</TableHead>
            <TableHead>{i18n.t(k.CONNECTORS)}</TableHead>
            <TableHead>{i18n.t(k.USERS)}</TableHead>
            <TableHead>{i18n.t(k.STATUS)}</TableHead>
            <TableHead>{i18n.t(k.DELETE)}</TableHead>
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
                      i18n.t(k._)
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
                              {i18n.t(k._9)}{" "}
                              {userGroup.users.length - MAX_USERS_TO_DISPLAY}{" "}
                              {i18n.t(k.MORE)}
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      i18n.t(k._)
                    )}
                  </TableCell>
                  <TableCell>
                    {userGroup.is_up_to_date ? (
                      <div className="text-success">
                        {i18n.t(k.UP_TO_DATE1)}
                      </div>
                    ) : (
                      <div className="w-10">
                        <LoadingAnimation text="Синхронизация" />
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
                            message: `${i18n.t(k.USER_GROUP1)}${
                              userGroup.name
                            }${i18n.t(k.DELETED)}`,
                            type: "success",
                          });
                        } else {
                          const errorMsg = (await response.json()).detail;
                          setPopup({
                            message: `${i18n.t(
                              k.FAILED_TO_DELETE_USER_GROUP
                            )} ${errorMsg}`,
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
            header: i18n.t(k.NAME),
            key: "name",
          },
          {
            header: i18n.t(k.CONNECTORS),
            key: "ccPairs",
          },
          {
            header: i18n.t(k.USERS),
            key: "users",
          },
          {
            header: i18n.t(k.STATUS),
            key: "status",
          },
          {
            header: i18n.t(k.DELETE),
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
                        {i18n.t(k._9)}{" "}
                        {userGroup.users.length - MAX_USERS_TO_DISPLAY}{" "}
                        {i18n.t(k.MORE)}
                      </div>
                    </div>
                  )}
                </div>
              ),

              status: userGroup.is_up_to_date ? (
                <div className="text-emerald-600">{i18n.t(k.UP_TO_DATE1)}</div>
              ) : (
                <div className="text-text-300 w-10">
                  <LoadingAnimation text="Синхронизация" />
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
                        message: `${i18n.t(k.USER_GROUP1)}${
                          userGroup.name
                        }${i18n.t(k.DELETED)}`,
                        type: "success",
                      });
                    } else {
                      const errorMsg = (await response.json()).detail;
                      setPopup({
                        message: `${i18n.t(
                          k.FAILED_TO_DELETE_USER_GROUP
                        )} ${errorMsg}`,
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
