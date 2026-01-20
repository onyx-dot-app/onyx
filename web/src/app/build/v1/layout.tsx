import { BuildProvider } from "@/app/build/contexts/BuildContext";
import { UploadFilesProvider } from "@/app/build/contexts/UploadFilesContext";
import BuildSidebar from "@/app/build/components/SideBar";

export interface LayoutProps {
  children: React.ReactNode;
}

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
        <div className="flex flex-row w-full h-full">
          <BuildSidebar />
          {children}
        </div>
      </BuildProvider>
    </UploadFilesProvider>
  );
}
