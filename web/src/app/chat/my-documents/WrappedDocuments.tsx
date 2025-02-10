"use client";

import Title from "@/components/ui/title";
import SidebarWrapper from "../../assistants/SidebarWrapper";
import MyDocuments from "./MyDocuments";

export default function WrappedUserDocuments({}: {}) {
  return (
    <SidebarWrapper size="lg">
      <div className="mx-auto w-full">
        <MyDocuments />
      </div>
    </SidebarWrapper>
  );
}
