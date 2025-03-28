"use client";

import SidebarWrapper from "@/app/assistants/SidebarWrapper";
import { AssistantStats } from "./AssistantStats";

export default function WrappedAssistantsStats({
  assistantId,
}: {
  assistantId: number;
}) {
  return (
    <SidebarWrapper>
      <AssistantStats assistantId={assistantId} />
    </SidebarWrapper>
  );
}
