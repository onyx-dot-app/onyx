"use client";

import { useTranslations } from "next-intl";
import { Tag, Text, type TagColor } from "@opal/components";
import type { MethodSpec } from "@/lib/tools/types";

type OpenApiMethodColor = Extract<TagColor, "green" | "red" | "blue">;

/** An HTTP method's color: green for reads, red for deletes, blue otherwise. */
export function openApiMethodColor(method: string): OpenApiMethodColor {
  const verb = method.toUpperCase();
  return verb === "GET" ? "green" : verb === "DELETE" ? "red" : "blue";
}

/** The CSS color of each method color, for elements that are not a `Tag`. */
export const OPENAPI_METHOD_CSS_COLORS: Record<OpenApiMethodColor, string> = {
  green: "var(--theme-green-05)",
  red: "var(--status-error-05)",
  blue: "var(--theme-blue-05)",
};

interface OpenAPIMethodPathProps {
  method: Pick<MethodSpec, "method" | "path">;
}

/** An action's HTTP method tag and its endpoint path. */
export function OpenAPIMethodPath({ method }: OpenAPIMethodPathProps) {
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

interface OpenAPIEndpointListProps {
  methods: readonly Pick<MethodSpec, "method" | "path" | "name" | "summary">[];
}

export default function OpenAPIEndpointList({
  methods,
}: OpenAPIEndpointListProps) {
  const t = useTranslations("actions.addOpenApiModal.method");
  return (
    <ul className="m-0 list-none divide-y divide-border-01 p-0">
      {methods.map((method) => (
        <li
          key={`${method.method}-${method.path}-${method.name}`}
          className="flex min-w-0 flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between sm:gap-4"
        >
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <Text
              font="main-ui-action"
              color="text-05"
              wordWrap="wrap-anywhere"
            >
              {method.name}
            </Text>
            <Text
              font="secondary-body"
              color="text-03"
              wordWrap="wrap-anywhere"
            >
              {method.summary || t("noSummary")}
            </Text>
          </div>
          <div className="sm:max-w-[50%]">
            <OpenAPIMethodPath method={method} />
          </div>
        </li>
      ))}
    </ul>
  );
}
