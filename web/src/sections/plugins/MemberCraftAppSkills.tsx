"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, InputTypeIn, Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import useUserSkills from "@/hooks/useUserSkills";

interface MemberCraftAppSkillsProps {
  appId: number;
}

export default function MemberCraftAppSkills({
  appId,
}: MemberCraftAppSkillsProps) {
  const t = useTranslations("actions.memberPlugins.appSkills");
  const state = useTranslations("actions.memberPlugins.state");
  const { data, isLoading, error, refresh } = useUserSkills();
  const [search, setSearch] = useState("");
  const query = search.trim().toLocaleLowerCase();
  const skills = [...(data?.builtins ?? []), ...(data?.customs ?? [])].filter(
    (skill) => skill.external_app?.external_app_id === appId
  );
  const visible = skills.filter((skill) =>
    [skill.name, skill.description].some((value) =>
      value.toLocaleLowerCase().includes(query)
    )
  );

  const loadError = error ? (
    <div className="flex items-center justify-between gap-4" role="alert">
      <Text font="secondary-body" color="text-03">
        {t("error")}
      </Text>
      <Button prominence="secondary" size="sm" onClick={() => void refresh()}>
        {state("retry")}
      </Button>
    </div>
  ) : null;
  if (error && !data) return loadError;

  if (isLoading && !data) {
    return (
      <div role="status">
        <Text font="secondary-body" color="text-03">
          {t("loading")}
        </Text>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {loadError}
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <InputTypeIn
            searchIcon
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("search")}
            aria-label={t("search")}
          />
        </div>
        <Text font="secondary-body" color="text-03">
          {t("count", { count: visible.length })}
        </Text>
      </div>
      {visible.length ? (
        <ul className="m-0 list-none divide-y divide-border-01 rounded-12 border border-border-01 p-0">
          {visible.map((skill) => (
            <li key={`${skill.source}:${skill.id}`} className="px-4 py-3">
              <ContentAction
                sizePreset="main-ui"
                variant="section"
                padding={0}
                title={skill.name}
                titleMaxLines={1}
                description={skill.description}
                descriptionMaxLines={2}
                rightChildren={
                  <Text font="secondary-body" color="text-03">
                    {t(skill.enabled ? "enabled" : "disabled")}
                  </Text>
                }
              />
            </li>
          ))}
        </ul>
      ) : (
        <Text font="secondary-body" color="text-03">
          {t(skills.length ? "noMatches" : "empty")}
        </Text>
      )}
    </div>
  );
}
