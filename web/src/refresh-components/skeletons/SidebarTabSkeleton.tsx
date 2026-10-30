import { LineLoader } from "@opal/loaders";
import { cn } from "@opal/utils";

interface SidebarTabSkeletonProps {
  textWidth?: string;
  folded?: boolean;
}

/**
 * A sidebar tab that has not loaded. It is decorative: give the group of
 * skeletons one `role="status"` with a label.
 */
export default function SidebarTabSkeleton({
  textWidth = "w-2/3",
  folded,
}: SidebarTabSkeletonProps) {
  return (
    <div aria-hidden className="w-full rounded-08 p-1.5">
      <div className="h-6 flex flex-row items-center px-1 py-0.5">
        {folded ? (
          <div className="opal-shimmer-block h-4 w-4 rounded-full" />
        ) : (
          <div className={textWidth}>
            <LineLoader />
          </div>
        )}
      </div>
    </div>
  );
}
