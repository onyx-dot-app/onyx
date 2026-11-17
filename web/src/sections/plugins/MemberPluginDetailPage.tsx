"use client";

import { useLocale, useTranslations } from "next-intl";
import { Badge, Button, Card, Tabs } from "@opal/components";
import { Content, Section, SettingsLayouts } from "@opal/layouts";
import { SvgArrowLeft } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  memberPluginEntries,
  memberPluginHref,
  parseMemberPluginTab,
  pendingIntegrations,
  type MemberPluginEntry,
  type MemberPluginTab,
} from "@/lib/plugins/directory";
import { canChangeOrganizationAccess } from "@/lib/skills/sharing";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import AlwaysAllowList from "@/sections/plugins/AlwaysAllowList";
import IntegrationConnectionRow from "@/sections/plugins/IntegrationConnectionRow";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";

interface OverviewTabProps {
  entry: MemberPluginEntry;
}

function OverviewTab({ entry }: OverviewTabProps) {
  const t = useTranslations("plugins.member.detail.overview");
  const sections = useTranslations("plugins.member.sections");
  return (
    <Card padding={4}>
      <Section gap={4} alignItems="stretch" height="auto">
        <Content
          title={entry.name}
          description={entry.description ?? t("noDescription")}
        />
        <Content
          font="secondary-body"
          title={t("location")}
          description={sections(entry.section)}
        />
        {entry.ownerEmail && (
          <Content
            font="secondary-body"
            title={t("owner")}
            description={entry.ownerEmail}
          />
        )}
        {entry.skills.length > 0 && (
          <Content
            font="secondary-body"
            title={t("skills")}
            description={entry.skills.map((skill) => skill.name).join(", ")}
          />
        )}
        {entry.integrations.length > 0 && (
          <Content
            font="secondary-body"
            title={t("integrations")}
            description={entry.integrations
              .map((integration) => integration.name)
              .join(", ")}
          />
        )}
      </Section>
    </Card>
  );
}

function SkillsTab({ entry }: OverviewTabProps) {
  const t = useTranslations("plugins.member.detail.skills");
  return (
    <Section gap={2} alignItems="stretch" height="auto">
      {entry.skills.map((skill) => (
        <Card key={skill.id} padding={4}>
          <Content
            title={skill.name}
            description={skill.description}
            badge={
              skill.is_valid === false
                ? { title: t("invalid"), color: "error" }
                : !skill.enabled
                  ? { title: t("off") }
                  : undefined
            }
          />
        </Card>
      ))}
    </Section>
  );
}

interface IntegrationsTabProps {
  entry: MemberPluginEntry;
}

function IntegrationsTab({ entry }: IntegrationsTabProps) {
  const returnPath = memberPluginHref(entry.id, "integrations");
  return (
    <Section gap={2} alignItems="stretch" height="auto">
      {entry.integrations.map((integration) => (
        <Card key={integration.id} padding={2}>
          <Section gap={2} alignItems="stretch" height="auto">
            <IntegrationConnectionRow
              integration={integration}
              returnPath={returnPath}
              allowDisconnect
            />
            {integration.users_can_save_always_allow && (
              <Section padding={2} alignItems="stretch" height="auto">
                <AlwaysAllowList integrationId={integration.id} />
              </Section>
            )}
          </Section>
        </Card>
      ))}
    </Section>
  );
}

interface MemberPluginDetailPageProps {
  pluginId: string;
}

/** One plugin of the member Plugins page: Overview, Skills, Integrations and
 * Versions. Tabs with nothing to show are hidden. */
export default function MemberPluginDetailPage({
  pluginId,
}: MemberPluginDetailPageProps) {
  const t = useTranslations("plugins.member.detail");
  const locale = useLocale();
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const { user } = useUser();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const skills = useUserSkills();
  const integrations = useMemberIntegrations();
  const entry = memberPluginEntries(
    skills.data?.customs ?? [],
    integrations.data ?? [],
    user?.email ?? null,
    locale
  ).find((candidate) => candidate.id === pluginId);
  const loading = skills.isLoading || integrations.isLoading;
  const skill = entry?.skills.length === 1 ? entry.skills[0] : undefined;
  const showVersions =
    skill !== undefined &&
    (skill.user_permission === "OWNER" || skill.user_permission === "EDITOR");
  const available: MemberPluginTab[] = [
    "overview",
    ...(entry && entry.skills.length > 0 ? (["skills"] as const) : []),
    ...(entry && entry.integrations.length > 0
      ? (["integrations"] as const)
      : []),
    ...(showVersions ? (["versions"] as const) : []),
  ];
  const requested = parseMemberPluginTab(searchParams.get("tab"));
  const tab = available.includes(requested) ? requested : "overview";
  const pending = entry ? pendingIntegrations(entry.integrations).length : 0;

  return (
    <SettingsLayouts.Root
      width="lg"
      loading={loading}
      error={
        loading
          ? false
          : skills.error || integrations.error
            ? t("loadFailed")
            : entry
              ? false
              : t("notFound")
      }
    >
      <SettingsLayouts.Header
        title={entry?.name ?? t("title")}
        description={entry?.description ?? undefined}
        actions={[
          <Button
            key="back"
            prominence="secondary"
            icon={SvgArrowLeft}
            {...navigation.linkTo("/app/plugins")}
          >
            {t("back")}
          </Button>,
          ...(pending > 0
            ? [
                <Badge
                  key="pending"
                  size={6}
                  color="warning"
                  title={t("pending", { count: pending })}
                />,
              ]
            : []),
        ]}
      />
      <SettingsLayouts.Body>
        {entry && (
          <Tabs
            value={tab}
            onValueChange={(value) =>
              navigation.go(
                memberPluginHref(entry.id, parseMemberPluginTab(value)),
                { replace: true, scroll: false }
              )
            }
            variant="contained"
            gap={6}
          >
            <Tabs.List>
              {available.map((value) => (
                <Tabs.Trigger key={value} value={value}>
                  {t(`tabs.${value}`)}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
            <Tabs.Content value="overview">
              <OverviewTab entry={entry} />
            </Tabs.Content>
            {available.includes("skills") && (
              <Tabs.Content value="skills">
                <SkillsTab entry={entry} />
              </Tabs.Content>
            )}
            {available.includes("integrations") && (
              <Tabs.Content value="integrations">
                <IntegrationsTab entry={entry} />
              </Tabs.Content>
            )}
            {skill && showVersions && (
              <Tabs.Content value="versions">
                <SkillVersionsTab
                  skill={skill}
                  canPublish={canChangeOrganizationAccess(
                    skill,
                    isGlobalHolder
                  )}
                  onChanged={() => void skills.refresh()}
                />
              </Tabs.Content>
            )}
          </Tabs>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
