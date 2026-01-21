"use client";

import {
  BuildProvider,
  useBuildContext,
} from "@/app/build/contexts/BuildContext";
import { UploadFilesProvider } from "@/app/build/contexts/UploadFilesContext";
import BuildSidebar from "@/app/build/components/SideBar";
import VideoBackground from "@/app/build/v1/components/VideoBackground";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgSidebar } from "@opal/icons";
import useScreenSize from "@/hooks/useScreenSize";
import { cn } from "@/lib/utils";

function BuildMobileHeader() {
  const { setLeftSidebarFolded, leftSidebarFolded } = useBuildContext();
  const { isMobile } = useScreenSize();

  // Only show on mobile when sidebar is folded
  if (!isMobile || !leftSidebarFolded) return null;

  return (
    <div className="w-full flex flex-row items-center py-3 px-4 h-16">
      <IconButton
        icon={SvgSidebar}
        onClick={() => setLeftSidebarFolded(false)}
        internal
      />
    </div>
  );
}

/**
 * Build V1 Layout - Skeleton pattern with 3-panel layout
 *
 * Wraps with BuildProvider and UploadFilesProvider (for file uploads).
 * Includes BuildSidebar on the left with video background.
 * Pre-provisioning is handled by useBuildSessionController.
 * The page component provides the center (chat) and right (output) panels.
 */
function BuildLayoutInner({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-row w-full h-full">
      <BuildSidebar />
      <div className="relative flex-1 h-full overflow-hidden">
        <VideoBackground />
        <div className="relative z-10 flex flex-col w-full h-full backdrop-blur-sm">
          <BuildMobileHeader />
          <div className="flex-1 overflow-hidden">{children}</div>
        </div>
      </div>
    </div>
  );
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <UploadFilesProvider>
      <BuildProvider>
        <BuildLayoutInner>{children}</BuildLayoutInner>
      </BuildProvider>
    </UploadFilesProvider>
  );
}
