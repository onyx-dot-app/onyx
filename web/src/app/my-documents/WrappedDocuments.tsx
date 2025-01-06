"use client";

import { AssistantsPageTitle } from "../assistants/AssistantsPageTitle";
import SidebarWrapper from "../assistants/SidebarWrapper";
import MyDocuments from "./MyDocuments";

export default function WrappedUserDocuments({
  initiallyToggled,
}: {
  initiallyToggled: boolean;
}) {
  return (
    <SidebarWrapper size="lg" page="chat" initiallyToggled={initiallyToggled}>
      <div className="mx-auto w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar">
        <AssistantsPageTitle>My Documents</AssistantsPageTitle>
        <MyDocuments />
      </div>
    </SidebarWrapper>
  );
}
