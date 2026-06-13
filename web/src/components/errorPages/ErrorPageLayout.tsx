import React from "react";
import { APP_NAME } from "@/lib/brand";

interface ErrorPageLayoutProps {
  children: React.ReactNode;
}

export default function ErrorPageLayout({ children }: ErrorPageLayoutProps) {
  return (
    <div className="flex flex-col items-center justify-center w-full h-screen gap-4">
      <div className="flex items-center gap-3" aria-label={APP_NAME}>
        <div className="h-12 w-12 rounded-12 bg-theme-primary-05 text-text-inverted-05 flex items-center justify-center text-2xl font-bold">
          G
        </div>
        <span className="text-3xl font-semibold text-text-05">{APP_NAME}</span>
      </div>
      <div className="max-w-160 w-full border bg-background-neutral-00 shadow-02 rounded-16 p-6 flex flex-col gap-4">
        {children}
      </div>
    </div>
  );
}
