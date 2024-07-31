"use client";

import SidebarWrapper from "../SidebarWrapper";
import { ChatSession } from "@/app/chat/interfaces";
import { Folder } from "@/app/chat/folders/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { AssistantsGallery } from "./AssistantsGallery";

export default function WrappedAssistantsGallery({
  chatSessions,
  initiallyToggled,
  folders,
  openedFolders,
  user,
  assistants,
}: {
  chatSessions: ChatSession[];
  folders: Folder[];
  initiallyToggled: boolean;
  openedFolders?: { [key: number]: boolean };
  user: User | null;
  assistants: Persona[];
}) {
  return (
    <SidebarWrapper
      page="chat"
      initiallyToggled={initiallyToggled}
      chatSessions={chatSessions}
      folders={folders}
      openedFolders={openedFolders}
      headerProps={{ user, page: "chat" }}
      contentProps={{
        assistants: assistants,
        user: user,
      }}
      content={(contentProps) => (
        <AssistantsGallery
          assistants={contentProps.assistants}
          user={contentProps.user}
        />
      )}
    />
  );
}
