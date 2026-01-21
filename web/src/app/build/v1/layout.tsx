"use client";

import { BuildProvider } from "@/app/build/contexts/BuildContext";
import { UploadFilesProvider } from "@/app/build/contexts/UploadFilesContext";
import { usePreProvisioning } from "@/app/build/hooks/usePreProvisioning";
import BuildSidebar from "@/app/build/components/SideBar";

/**
 * Build V1 Layout - Skeleton pattern with 3-panel layout
 *
 * Wraps with BuildProvider and UploadFilesProvider (for file uploads).
 * Includes BuildSidebar on the left.
 * Uses usePreProvisioning to start sandbox provisioning in background.
 * The page component provides the center (chat) and right (output) panels.
 */
export default function Layout({ children }: { children: React.ReactNode }) {
  usePreProvisioning();

  return (
    <UploadFilesProvider>
      <BuildProvider>
        <div className="flex flex-row w-full h-full">
          <BuildSidebar />
          {children}
        </div>
      </BuildProvider>
    </UploadFilesProvider>
  );
}
