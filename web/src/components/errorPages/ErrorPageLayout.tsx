import React from "react";
import { OnyxLogoTypeIcon } from "@/components/icons/icons";

interface ErrorPageLayoutProps {
  children: React.ReactNode;
}

export default function ErrorPageLayout({ children }: ErrorPageLayoutProps) {
  return (
    <div className="flex flex-col items-center justify-center w-full h-screen gap-4">
      <OnyxLogoTypeIcon size={120} className="" />
      <div className="max-w-[40rem] w-full border bg-background-neutral-00 shadow-02 rounded-16 p-6 flex flex-col gap-4">
        {children}
      </div>
    </div>
  );
}
