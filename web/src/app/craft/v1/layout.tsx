"use client";

import { BuildProvider } from "@/app/craft/contexts/BuildContext";
import { UploadFilesProvider } from "@/app/craft/contexts/UploadFilesContext";
import { BuildOnboardingProvider } from "@/app/craft/onboarding/BuildOnboardingProvider";
import BuildSidebar from "@/app/craft/components/SideBar";

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
        <BuildOnboardingProvider>
          <div className="flex flex-row w-full h-full">
            <BuildSidebar />
            {children}
          </div>
        </BuildOnboardingProvider>
      </BuildProvider>
    </UploadFilesProvider>
  );
}
