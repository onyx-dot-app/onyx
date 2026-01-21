import { BuildProvider } from "@/app/build/contexts/BuildContext";
import { UploadFilesProvider } from "@/app/build/contexts/UploadFilesContext";
import BuildSidebar from "@/app/build/components/SideBar";

export interface LayoutProps {
  children: React.ReactNode;
}

const VIDEO_BACKGROUND_PATH = "https://cdn.onyx.app/build/background.mp4";

/**
 * Build V1 Layout - Skeleton pattern with 3-panel layout
 *
 * Wraps with BuildProvider and UploadFilesProvider (for file uploads).
 * Includes BuildSidebar on the left.
 * The page component provides the center (chat) and right (output) panels.
 */
export default function Layout({ children }: LayoutProps) {
  return (
    <UploadFilesProvider>
      <BuildProvider>
        <div className="relative flex flex-row w-full h-full overflow-hidden">
          {/* Video Background */}
          <video
            autoPlay
            loop
            muted
            playsInline
            className="absolute inset-0 w-full h-full object-cover z-0 pointer-events-none opacity-50"
          >
            <source src={VIDEO_BACKGROUND_PATH} type="video/mp4" />
          </video>

          {/* Content layer */}
          <div className="relative z-10 flex flex-row w-full h-full">
            <BuildSidebar />
            {children}
          </div>
        </div>
      </BuildProvider>
    </UploadFilesProvider>
  );
}
