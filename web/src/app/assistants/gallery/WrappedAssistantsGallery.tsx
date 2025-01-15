"use client";

import SidebarWrapper from "../SidebarWrapper";
import { AssistantsGallery } from "./AssistantsGallery";

export default function WrappedAssistantsGallery({
  toggleSidebar,
}: {
  toggleSidebar: boolean;
}) {
  return (
    <SidebarWrapper page="chat" initiallyToggled={toggleSidebar}>
      <AssistantsGallery />
    </SidebarWrapper>
  );
}
