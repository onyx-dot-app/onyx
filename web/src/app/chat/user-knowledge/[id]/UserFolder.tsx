"use client";

import SidebarWrapper from "@/app/assistants/SidebarWrapper";
import UserFolderContent from "./UserFolderContent";
import { BackButton } from "@/components/BackButton";

export default function WrappedUserFolders({
  userFileId,
}: {
  userFileId: string;
}) {
  return (
    <div className="mx-auto w-full">
      <div className="absolute top-4 left-4">
        <BackButton />
      </div>
      <UserFolderContent folderId={Number(userFileId)} />
    </div>
  );
}
