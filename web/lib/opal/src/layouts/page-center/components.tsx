import type React from "react";

interface PageCenterProps {
  /** What sits in the middle of the page, e.g. a loader or an empty state. */
  children: React.ReactNode;
}

/**
 * Centres its children in the page body, both ways. The frame is at least
 * 60% of the viewport tall, so it centres even when the body around it has
 * no set height. Use it for whole-body states: loading, errors, empty pages.
 */
function PageCenter({ children }: PageCenterProps) {
  return (
    <div className="flex h-full min-h-[60vh] w-full flex-col items-center justify-center">
      {children}
    </div>
  );
}

export { PageCenter, type PageCenterProps };
