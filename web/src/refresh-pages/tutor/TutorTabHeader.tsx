"use client";

import { Content } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface TutorTabHeaderProps {
  icon: IconFunctionComponent;
  title: string;
  description?: string;
  rightChildren?: ReactNode;
  children?: ReactNode;
  contentClassName?: string;
}

export default function TutorTabHeader({
  icon,
  title,
  description,
  rightChildren,
  children,
  contentClassName,
}: TutorTabHeaderProps) {
  return (
    <header className="shrink-0 border-b border-border-01 bg-background-neutral-01">
      <div
        className={cn(
          "mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-3 md:px-6",
          contentClassName
        )}
      >
        <div className="flex min-h-10 flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <Content
              icon={icon}
              title={title}
              description={description}
              sizePreset="main-ui"
              variant="section"
            />
          </div>
          {rightChildren && (
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {rightChildren}
            </div>
          )}
        </div>

        {children}
      </div>
    </header>
  );
}
