"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { InputTypeIn, Text } from "@opal/components";
import MCPToolRow from "@/sections/plugins/MCPToolRow";
import type { ToolSnapshot } from "@/lib/tools/types";

interface MemberMCPToolsListProps {
  tools: readonly (Pick<
    ToolSnapshot,
    "name" | "display_name" | "description"
  > & { id: string | number })[];
}

export default function MemberMCPToolsList({ tools }: MemberMCPToolsListProps) {
  const t = useTranslations("actions");
  const [search, setSearch] = useState("");
  const query = search.trim().toLocaleLowerCase();
  const visible = tools.filter((tool) =>
    [tool.name, tool.display_name, tool.description].some((value) =>
      value?.toLocaleLowerCase().includes(query)
    )
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <InputTypeIn
        searchIcon
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={t("mcpTools.search")}
        aria-label={t("mcpTools.search")}
      />
      <Text font="secondary-body" color="text-03">
        {t("memberPlugins.detail.toolCount", { count: visible.length })}
      </Text>
      {visible.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {visible.map((tool) => (
            <MCPToolRow key={tool.id} tool={tool} />
          ))}
        </ul>
      ) : (
        <Text font="secondary-body" color="text-03">
          {t(
            tools.length
              ? "toolsList.empty.searchMessage"
              : "memberPlugins.detail.noTools"
          )}
        </Text>
      )}
    </div>
  );
}
