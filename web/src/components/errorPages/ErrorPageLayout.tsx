import React from "react";
import { LogoType } from "../logo/Logo";

interface ErrorPageLayoutProps {
  children: React.ReactNode;
}

export default function ErrorPageLayout({ children }: ErrorPageLayoutProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen">
      <div className="mb-4 flex items-center max-w-[220px]">
        <LogoType size="large" />
      </div>
      <div className="max-w-xl border border-border w-full bg-white shadow-md rounded-lg overflow-hidden">
        <div className="p-6 sm:p-8">{children}</div>
      </div>
    </div>
  );
}
