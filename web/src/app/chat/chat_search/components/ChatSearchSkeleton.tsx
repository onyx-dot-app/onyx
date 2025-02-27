import React from "react";

export function ChatSearchItemSkeleton() {
  return (
    <div className="animate-pulse px-4 py-3 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg">
      <div className="flex items-center">
        <div className="h-5 w-5 rounded-full bg-neutral-200 dark:bg-neutral-700"></div>
        <div className="ml-4 flex-1">
          <div className="h-2 my-1 w-3/4 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
          <div className="mt-2 h-3 w-1/2 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
        </div>
      </div>
    </div>
  );
}

export function ChatSearchSkeletonList() {
  return (
    <div>
      {[...Array(5)].map((_, index) => (
        <ChatSearchItemSkeleton key={index} />
      ))}
    </div>
  );
}
