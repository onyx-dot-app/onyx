"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSwitch,
  InputTypeIn,
  Text,
  Tooltip,
} from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import useUserSkills from "@/hooks/useUserSkills";
import type { Skill } from "@/lib/skills/types";

interface MemberCraftAppSkillsProps {
  appId: number;
  changes: Record<string, boolean>;
  onChange: (skill: Skill, enabled: boolean) => void;
  disabled: boolean;
  onPreview: (skill: Skill) => void;
}

export default function MemberCraftAppSkills({
  appId,
  changes,
  onChange,
  disabled,
  onPreview,
}: MemberCraftAppSkillsProps) {
  const t = useTranslations("actions.memberPlugins.appSkills");
  const cards = useTranslations("cards.skill");
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

      <InputTypeIn
        searchIcon
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={t("search")}
        aria-label={t("search")}
      />

      <Text font="secondary-body" color="text-03">
        {t("count", { count: visible.length })}
      </Text>

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
                  <Section
                    flexDirection="row"
                    justifyContent="start"
                    alignItems="center"
                    gap={3}
                    width="auto"
                    height="auto"
                  >
                    <Button
                      prominence="secondary"
                      size="sm"
                      disabled={disabled}
                      onClick={() => onPreview(skill)}
                    >
                      {t("preview")}
                    </Button>
                    <Tooltip tooltip={skill.unavailable_reason ?? undefined}>
                      <InputSwitch
                        checked={changes[skill.id] ?? skill.enabled}
                        onCheckedChange={(enabled) => onChange(skill, enabled)}
                        disabled={
                          disabled ||
                          !skill.can_toggle ||
                          skill.is_valid === false
                        }
                        aria-label={cards(
                          (changes[skill.id] ?? skill.enabled)
                            ? "toggle.disable.ariaLabel"
                            : "toggle.enable.ariaLabel",
                          { name: skill.name }
                        )}
                      />
                    </Tooltip>
                  </Section>
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
