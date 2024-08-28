import { UserGroupUpdate, SetCuratorRequest } from "../types";

export const updateUserGroup = async (
  groupId: number,
  userGroup: UserGroupUpdate
) => {
  const url = `/api/manage/admin/user-group/${groupId}`;
  return await fetch(url, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(userGroup),
  });
};

export const updateCuratorStatus = async (
  groupId: number,
  curatorRequest: SetCuratorRequest
) => {
  const url = `/api/manage/admin/user-group/${groupId}/set-curator`;
  return await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(curatorRequest),
  });
};
