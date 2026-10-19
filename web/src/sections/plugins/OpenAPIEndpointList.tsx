"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import type { MethodSpec } from "@/lib/tools/types";
import { OpenAPIMethodPath } from "@/lib/plugins/components";
import { sortByOpenApiMethod } from "@/lib/plugins/openapi/methods";

interface OpenAPIEndpointListProps {
  methods: readonly Pick<MethodSpec, "method" | "path" | "name" | "summary">[];
}

export default function OpenAPIEndpointList({
  methods,
}: OpenAPIEndpointListProps) {
  const t = useTranslations("actions.addOpenApiModal.method");
  return (
    <ul className="m-0 list-none divide-y divide-border-01 p-0">
      {sortByOpenApiMethod(methods).map((method) => (
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
