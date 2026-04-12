"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { UserGroup } from "@/lib/types";
import Separator from "@/refresh-components/Separator";
import GroupCard from "./GroupCard";
import { isBuiltInGroup } from "./utils";
import { Section } from "@/layouts/general-layouts";
import { IllustrationContent } from "@opal/layouts";
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
        title={t("noGroupsFound")}
        description={t("noGroupsMatch", { query: searchQuery })}
      />
    );
  }

  const builtInGroups = filtered.filter(isBuiltInGroup);
  const customGroups = filtered.filter((g) => !isBuiltInGroup(g));

  return (
    <Section flexDirection="column" gap={0.5}>
      {builtInGroups.map((group) => (
        <GroupCard key={group.id} group={group} />
      ))}

      {builtInGroups.length > 0 && customGroups.length > 0 && (
        <Separator paddingYRem={0.5} />
      )}

      {customGroups.map((group) => (
        <GroupCard key={group.id} group={group} />
      ))}
    </Section>
  );
}

export default GroupsList;
