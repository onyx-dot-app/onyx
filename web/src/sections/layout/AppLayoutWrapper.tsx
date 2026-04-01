"use client";

import { useEmbeddedMode } from "@/hooks/useEmbeddedMode";
import AppSidebar from "@/sections/sidebar/AppSidebar";

interface AppLayoutWrapperProps {
  children: React.ReactNode;
}

/**
 * Client wrapper for the main app layout that conditionally renders
 * the sidebar. In embedded mode (LTI iframe), the sidebar and all
 * navigation chrome are hidden so only the chat panel is visible.
 */
export function AppLayoutWrapper({ children }: AppLayoutWrapperProps) {
  const isEmbedded = useEmbeddedMode();

  return (
    <div className="flex flex-row w-full h-full">
      {!isEmbedded && <AppSidebar />}
      {children}
    </div>
  );
}
