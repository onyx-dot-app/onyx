"use client";

import { Tag, Text } from "@opal/components";
import type { MethodSpec } from "@/lib/tools/types";
import { openApiMethodColor } from "@/lib/plugins/openapi/methods";

export interface OpenAPIMethodPathProps {
  method: Pick<MethodSpec, "method" | "path">;
}

/** An action's HTTP method tag above its endpoint path, end-aligned. */
export default function OpenAPIMethodPath({ method }: OpenAPIMethodPathProps) {
  return (
    <div className="flex min-w-0 flex-col items-end gap-1">
      <Tag
        title={method.method.toUpperCase()}
        color={openApiMethodColor(method.method)}
      />
      <Text font="secondary-mono" color="text-03" wordWrap="wrap-anywhere">
        {method.path}
      </Text>
    </div>
  );
}
