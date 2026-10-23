"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { UserGroup } from "@/lib/types";
import { Divider } from "@opal/components";
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

  const builtInGroups = filtered.filter(isBuiltInGroup);
  const customGroups = filtered.filter((g) => !isBuiltInGroup(g));

  // The divider's own padding is the only space around it, so each list
  // spaces its cards on its own.
  return (
    <Section flexDirection="column" gap={0}>
      {builtInGroups.length > 0 && (
        <Section flexDirection="column" gap={2}>
          {builtInGroups.map((group) => (
            <GroupCard key={group.id} group={group} />
          ))}
        </Section>
      )}

      {builtInGroups.length > 0 && customGroups.length > 0 && (
        <Divider paddingPerpendicular={2} paddingParallel={0} />
      )}

      {customGroups.length > 0 && (
        <Section flexDirection="column" gap={2}>
          {customGroups.map((group) => (
            <GroupCard key={group.id} group={group} />
          ))}
        </Section>
      )}
    </Section>
  );
}

export default GroupsList;
