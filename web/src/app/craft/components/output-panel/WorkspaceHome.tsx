import type { ReactNode } from "react";
import { Text } from "@opal/components";
import type { RichStr } from "@opal/types";
import { cn } from "@opal/utils";

interface WorkspaceHomeProps {
  title: string | RichStr;
  children: ReactNode;
  wide?: boolean;
}

export function WorkspaceHome({
  title,
  children,
  wide = false,
}: WorkspaceHomeProps) {
  return (
    <div className="flex h-full items-start justify-center overflow-auto p-6 pt-8">
      <div
        className={cn(
          "flex w-full flex-col gap-1.5",
          wide ? "max-w-3xl @container" : "max-w-xs"
        )}
      >
        <div className="pb-3 text-center">
          <Text font="main-ui-muted" color="text-05">
            {title}
          </Text>
        </div>
        {children}
      </div>
    </div>
  );
}
