"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, InputTypeIn, MessageCard, SelectCard } from "@opal/components";
import {
  CardGrid,
  Content,
  ContentAction,
  IllustrationContent,
  Section,
  SettingsLayouts,
} from "@opal/layouts";
import { SvgBlocks, SvgChevronRight, SvgPlus, SvgSettings } from "@opal/icons";
import { SvgUnPlugged } from "@opal/illustrations";
import { useNavigation } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  filterPlugins,
  memberPluginEntries,
  memberPluginHref,
  pendingIntegrations,
  type MemberPluginEntry,
  type PluginFilter,
  type PluginSection,
} from "@/lib/plugins/directory";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import AddIntegrationModal from "@/sections/integrations/AddIntegrationModal";

const FILTERS: readonly PluginFilter[] = ["all", "skills", "integrations"];
const SECTIONS: readonly PluginSection[] = ["organization", "mine", "shared"];

interface MemberPluginRowProps {
  entry: MemberPluginEntry;
}

function MemberPluginRow({ entry }: MemberPluginRowProps) {
  const t = useTranslations("plugins.member.row");
  const navigation = useNavigation();
  const pending = pendingIntegrations(entry.integrations).length;
  const counts = [
    entry.skills.length > 0 && t("skillCount", { count: entry.skills.length }),
    entry.integrations.length > 0 &&
      t("integrationCount", { count: entry.integrations.length }),
  ].filter((count): count is string => typeof count === "string");
  return (
    <SelectCard
      border="solid"
      padding={2}
      role="button"
      tabIndex={0}
      aria-label={t("open.label", { name: entry.name })}
      onClick={() => navigation.go(memberPluginHref(entry.id))}
    >
      <ContentAction
        icon={SvgBlocks}
        title={entry.name}
        description={entry.description ?? counts.join(" · ")}
        badge={
          pending > 0
            ? {
                title: t("needsConnection", { count: pending }),
                color: "warning",
              }
            : undefined
        }
        rightChildren={
          <Section width="auto" height="auto" padding={1}>
            <SvgChevronRight size={16} />
          </Section>
        }
      />
    </SelectCard>
  );
}

export default function MemberPluginsPage() {
  const t = useTranslations("plugins.member");
  const locale = useLocale();
  const navigation = useNavigation();
  const { user } = useUser();
  const skills = useUserSkills();
  const integrations = useMemberIntegrations();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canAddIntegration = isGlobalHolder || isScopedManager;
  const [filter, setFilter] = useState<PluginFilter>("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);

  const entries = memberPluginEntries(
    skills.data?.customs ?? [],
    integrations.data ?? [],
    user?.email ?? null,
    locale
  );
  const shown = filterPlugins(entries, filter, query);
  const loading = skills.isLoading || integrations.isLoading;
  const failed = Boolean(skills.error || integrations.error);

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        title={t("title")}
        description={t("description")}
        stackActionsOnMobile
        actions={[
          ...(canAddIntegration
            ? [
                <Button
                  key="add"
                  icon={SvgPlus}
                  prominence="secondary"
                  onClick={() => setAdding(true)}
                >
                  {t("addIntegration.label")}
                </Button>,
              ]
            : []),
          ...(canAddIntegration
            ? [
                <Button
                  key="manage"
                  icon={SvgSettings}
                  prominence="tertiary"
                  {...navigation.linkTo("/admin/plugins")}
                >
                  {t("manage.label")}
                </Button>,
              ]
            : []),
        ]}
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="auto"
          gap={2}
          wrap
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            width="auto"
            height="auto"
            gap={1}
            role="group"
            aria-label={t("filters.label")}
          >
            {FILTERS.map((value) => (
              <Button
                key={value}
                size="sm"
                prominence={filter === value ? "primary" : "tertiary"}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {t(`filters.${value}.label`)}
              </Button>
            ))}
          </Section>
          <Section width={16} height="auto">
            <InputTypeIn
              icon="search"
              value={query}
              placeholder={t("search.placeholder")}
              aria-label={t("search.placeholder")}
              onChange={(event) => setQuery(event.target.value)}
            />
          </Section>
        </Section>
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        <Section gap={6} alignItems="stretch" height="auto">
          {failed && (
            <Section alignItems="start" gap={2} height="auto">
              <MessageCard variant="error" title={t("state.loadFailed")} />
              <Button
                prominence="secondary"
                onClick={() => {
                  void skills.refresh();
                  void integrations.mutate();
                }}
              >
                {t("state.retry.label")}
              </Button>
            </Section>
          )}
          {loading && (
            <MessageCard variant="pending" title={t("state.loading")} />
          )}
          {SECTIONS.map((section) => {
            const rows = shown.filter((entry) => entry.section === section);
            if (rows.length === 0) return null;
            return (
              <Section key={section} gap={2} alignItems="stretch" height="auto">
                <Content
                  font="main-ui-action"
                  title={t(`sections.${section}`)}
                />
                <CardGrid>
                  {rows.map((entry) => (
                    <MemberPluginRow key={entry.id} entry={entry} />
                  ))}
                </CardGrid>
              </Section>
            );
          })}
          {!loading && !failed && shown.length === 0 && (
            <Section gap={3} height="auto" padding={6}>
              <IllustrationContent
                illustration={SvgUnPlugged}
                title={
                  entries.length > 0
                    ? t("state.noResultsTitle")
                    : t("state.emptyTitle")
                }
                description={
                  entries.length > 0
                    ? t("state.noResultsDescription")
                    : t("state.emptyDescription")
                }
              />
              {entries.length > 0 && (
                <Button
                  prominence="secondary"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                  }}
                >
                  {t("state.clear.label")}
                </Button>
              )}
            </Section>
          )}
        </Section>
      </SettingsLayouts.Body>
      {adding && (
        <AddIntegrationModal
          canChooseOrganization={false}
          onClose={() => setAdding(false)}
          onCreated={(created) => {
            setAdding(false);
            void integrations.mutate();
            const plugin = created.plugins[0];
            if (plugin)
              navigation.go(memberPluginHref(plugin.plugin_id, "integrations"));
          }}
        />
      )}
    </SettingsLayouts.Root>
  );
}
