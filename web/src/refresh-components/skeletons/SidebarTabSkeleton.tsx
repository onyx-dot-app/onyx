import { cn } from "@opal/utils";

interface SidebarTabSkeletonProps {
  textWidth?: string;
  folded?: boolean;
}

export default function SidebarTabSkeleton({
  textWidth = "w-2/3",
  folded,
}: SidebarTabSkeletonProps) {
  return (
    <div className="w-full rounded-08 p-1.5">
      <div className="h-6 flex flex-row items-center px-1 py-0.5">
        <div
          className={cn(
            "bg-background-tint-04 animate-pulse",
            folded ? "h-4 w-4 rounded-full" : cn("h-3 rounded-sm", textWidth)
          )}
        />
      </div>
    </div>
  );
}
