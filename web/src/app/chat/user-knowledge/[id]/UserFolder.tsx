"use client";

import SidebarWrapper from "@/app/assistants/SidebarWrapper";
import UserFolderContent from "./UserFolderContent";

export default function WrappedUserFolders({
  userFileId,
}: {
  userFileId: string;
}) {
  return (
    <SidebarWrapper size="lg">
      <div className="mx-auto w-full">
        <UserFolderContent folderId={Number(userFileId)} />
      </div>
    </SidebarWrapper>
  );
}
