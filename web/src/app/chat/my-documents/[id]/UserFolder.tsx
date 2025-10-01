"use client";

import UserFolderContent from "./UserFolderContent";
import { BackButton } from "@/components/BackButton";
import { useRouter } from "next/navigation";
export default function WrappedUserFolders({
  userFileId,
}: {
  userFileId: string;
}) {
  const router = useRouter();
  return (
    <div className="mx-auto w-full">
      <div className="absolute top-4 left-4">
        <BackButton
          behaviorOverride={() => {
            router.push("/chat/my-documents");
          }}
        />
      </div>
      <UserFolderContent folderId={Number(userFileId)} />
    </div>
  );
}
