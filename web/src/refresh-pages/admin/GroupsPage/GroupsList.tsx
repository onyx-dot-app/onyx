"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { UserGroup } from "@/lib/types";
import { Divider } from "@opal/components";
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
  const { t } = useTranslation();
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return groups;
    const q = searchQuery.toLowerCase();
    return groups.filter((g) => g.name.toLowerCase().includes(q));
  }, [groups, searchQuery]);

  if (filtered.length === 0) {
    return (
      <IllustrationContent
        illustration={SvgNoResult}
        title={t("admin.groups.no_groups")}
        description={t("admin.groups.no_groups_search", { query: searchQuery })}
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
        <Divider paddingPerpendicular="sm" paddingParallel="fit" />
      )}

      {customGroups.map((group) => (
        <GroupCard key={group.id} group={group} />
      ))}
    </Section>
  );
}

export default GroupsList;
