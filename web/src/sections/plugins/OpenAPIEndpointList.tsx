"use client";

import MCPToolRow from "@/sections/plugins/MCPToolRow";
import type { MethodSpec } from "@/lib/tools/types";

type OpenAPIMethod = Pick<MethodSpec, "name" | "summary">;

export default function OpenAPIEndpointList({
  methods,
}: {
  methods: readonly OpenAPIMethod[];
}) {
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {methods.map((method) => (
        <MCPToolRow
          key={method.name}
          tool={{
            name: method.name,
            display_name: method.name,
            description: method.summary,
          }}
        />
      ))}
    </ul>
  );
}
