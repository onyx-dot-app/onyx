"use client";

import { TooltipProvider } from "@/components/ui/tooltip";

export function GlobalTooltipProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <TooltipProvider delayDuration={300} skipDelayDuration={200}>
      {children}
    </TooltipProvider>
  );
}
