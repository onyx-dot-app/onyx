"use client";
import { AssistantsList } from "./AssistantsList";
import SidebarWrapper from "../SidebarWrapper";

export default function WrappedAssistantsMine({
  initiallyToggled,
}: {
  initiallyToggled: boolean;
}) {
  return (
    <SidebarWrapper page="chat" initiallyToggled={initiallyToggled}>
      <AssistantsList />
    </SidebarWrapper>
  );
}
