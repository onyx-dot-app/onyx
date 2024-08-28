"use client";
import SidebarWrapper from "../SidebarWrapper";
import { ChatSession } from "@/app/chat/interfaces";
import { Folder } from "@/app/chat/folders/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";

import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { AssistantsPageTitle } from "../AssistantsPageTitle";
import { useInputPrompts } from "@/app/admin/prompt-library/hooks";
import { PromptSection } from "@/app/admin/prompt-library/promptSection";

export default function WrappedPrompts({
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
  const {
    data: promptLibrary,
    error: promptLibraryError,
    isLoading: promptLibraryIsLoading,
    refreshInputPrompts: refreshPrompts,
  } = useInputPrompts(false);

  return (
    <SidebarWrapper
      size="lg"
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
        <div className="mx-auto w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar">
          <AssistantsPageTitle>Prompt Gallery</AssistantsPageTitle>
          <PromptSection
            promptLibrary={promptLibrary || []}
            isLoading={promptLibraryIsLoading}
            error={promptLibraryError}
            refreshPrompts={refreshPrompts}
            isPublic={false}
            centering
          />
        </div>
      )}
    />
  );
}
