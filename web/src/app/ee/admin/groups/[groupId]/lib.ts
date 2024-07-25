import { UserGroupUpdate } from "../types";

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
