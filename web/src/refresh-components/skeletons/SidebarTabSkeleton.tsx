import { cn } from "@/lib/utils";

interface SidebarTabSkeletonProps {
  textWidth?: string;
}

export default function SidebarTabSkeleton({
  textWidth = "w-2/3",
}: SidebarTabSkeletonProps) {
  return (
    <div className="w-full rounded-08 p-1.5">
      <div className="h-[1.5rem] flex flex-row items-center px-1 py-0.5">
        <div
          className={cn(
            "h-3 rounded bg-background-tint-04 animate-pulse",
            textWidth
          )}
        />
      </div>
    </div>
  );
}
