"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { UserGroup } from "@/lib/types";
import GroupCard from "./GroupCard";
import { isBuiltInGroup } from "./utils";
import { IllustrationContent, Section } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";

interface GroupsListProps {
  groups: UserGroup[];
  searchQuery: string;
}

function GroupsList({ groups, searchQuery }: GroupsListProps) {
  const t = useTranslations("admin.groups");
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return groups;
    const q = searchQuery.toLowerCase();
    return groups.filter((g) => g.name.toLowerCase().includes(q));
  }, [groups, searchQuery]);

  if (filtered.length === 0) {
    return (
      <IllustrationContent
        illustration={SvgNoResult}
        title={t("list.noResults.title")}
        description={t("list.noResults.description", { query: searchQuery })}
      />
    );
  }

  // One flat list; the built-in groups lead.
  const ordered = [
    ...filtered.filter(isBuiltInGroup),
    ...filtered.filter((g) => !isBuiltInGroup(g)),
  ];

  return (
    <Section flexDirection="column" gap={2}>
      {ordered.map((group) => (
        <GroupCard key={group.id} group={group} />
      ))}
    </Section>
  );
}

export default GroupsList;
