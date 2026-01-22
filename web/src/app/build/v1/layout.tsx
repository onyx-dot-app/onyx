"use client";

import { BuildProvider } from "@/app/build/contexts/BuildContext";
import { UploadFilesProvider } from "@/app/build/contexts/UploadFilesContext";
import BuildSidebar from "@/app/build/components/SideBar";

/**
 * Build V1 Layout - Skeleton pattern with 3-panel layout
 *
 * Wraps with BuildProvider and UploadFilesProvider (for file uploads).
 * Includes BuildSidebar on the left.
 * Pre-provisioning is handled by useBuildSessionController.
 * The page component provides the center (chat) and right (output) panels.
 */
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <UploadFilesProvider>
      <BuildProvider>
        <div className="flex flex-row w-full h-full">
          <BuildSidebar />
          <div className="relative flex-1 h-full overflow-hidden">
            {children}
          </div>
        </div>
      </BuildProvider>
    </UploadFilesProvider>
  );
}
