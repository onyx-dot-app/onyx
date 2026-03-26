"use client";

import { use } from "react";
import EditGroupPage from "@/refresh-pages/admin/GroupsPage/EditGroupPage";

export default function EditGroupRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <EditGroupPage groupId={Number(id)} />;
}
