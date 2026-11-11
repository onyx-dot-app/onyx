"use client";

import type { ReactNode } from "react";
import { Text } from "@opal/components";
import type { ToolSnapshot } from "@/lib/tools/types";

export default function MCPToolRow({
  tool,
  control,
}: {
  tool: Pick<ToolSnapshot, "name" | "display_name" | "description">;
  control?: ReactNode;
}) {
  return (
    <li className="flex min-w-0 items-center justify-between gap-3">
      <div className="flex min-w-0 flex-1 flex-col">
        <Text font="main-ui-action" wordWrap="wrap-anywhere">
          {tool.display_name || tool.name}
        </Text>
        <Text font="secondary-body" color="text-03" wordWrap="wrap-anywhere">
          {tool.description}
        </Text>
      </div>
      {control}
    </li>
  );
}
