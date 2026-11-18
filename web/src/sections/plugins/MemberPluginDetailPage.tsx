"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Badge, Button, Card, InputSwitch, Tabs } from "@opal/components";
import {
  Content,
  InputHorizontal,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SvgArrowLeft, SvgOrganization, SvgShare } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import { publishPlugin, setPluginEnabled } from "@/lib/integrations/svc";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  memberPluginEntries,
  memberPluginHref,
  ownsPrivateIntegrationPlugin,
  parseMemberPluginTab,
  pendingIntegrations,
  pluginSwitch,
  type MemberPluginEntry,
  type MemberPluginTab,
} from "@/lib/plugins/directory";
import { setSkillEnabled } from "@/lib/skills/api";
import { canChangeOrganizationAccess } from "@/lib/skills/sharing";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import AlwaysAllowList from "@/sections/plugins/AlwaysAllowList";
import IntegrationConnectionRow from "@/sections/plugins/IntegrationConnectionRow";
import SharePluginModal from "@/sections/plugins/SharePluginModal";
import GenericConfirmModal from "@/sections/modals/GenericConfirmModal";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";

interface PluginTabProps {
  entry: MemberPluginEntry;
}

interface OverviewTabProps extends PluginTabProps {
  onChanged: () => Promise<void>;
}

function PluginSwitchCard({ entry, onChanged }: OverviewTabProps) {
  const t = useTranslations("plugins.member.detail.switch");
  const [busy, setBusy] = useState(false);
  const { enabled, blocked } = pluginSwitch(entry);
  const skill = entry.skills[0];

  async function change(next: boolean) {
    setBusy(true);
    try {
      if (skill) await setSkillEnabled(skill.id, next);
      else await setPluginEnabled(entry.id, next);
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card padding={4}>
      <InputHorizontal
        withLabel
        title={t("title")}
        description={blocked ? t(blocked) : t("description")}
        disabled={busy || blocked !== null}
      >
        <InputSwitch
          aria-label={t("label", { name: entry.name })}
          checked={enabled}
          disabled={busy || blocked !== null}
          onCheckedChange={(checked) => void change(checked)}
        />
      </InputHorizontal>
    </Card>
  );
}

function OverviewTab({ entry, onChanged }: OverviewTabProps) {
  const t = useTranslations("plugins.member.detail.overview");
  const sections = useTranslations("plugins.member.sections");
  return (
    <Section gap={4} alignItems="stretch" height="auto">
      <PluginSwitchCard entry={entry} onChanged={onChanged} />
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
    </Section>
  );
}

function SkillsTab({ entry }: PluginTabProps) {
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

function IntegrationsTab({ entry }: PluginTabProps) {
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

/** Tabs with nothing to show are hidden. */
export default function MemberPluginDetailPage({
  pluginId,
}: MemberPluginDetailPageProps) {
  const t = useTranslations("plugins.member.detail");
  const promptCopy = useTranslations("plugins.chat.connectPrompt");
  const locale = useLocale();
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const { user } = useUser();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const { isGlobalHolder: isActionManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const [sharing, setSharing] = useState(false);
  const [publishing, setPublishing] = useState(false);
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
  const owner = entry
    ? ownsPrivateIntegrationPlugin(entry, user?.email ?? null)
    : false;

  async function refresh(): Promise<void> {
    await Promise.all([skills.refresh(), integrations.mutate()]);
  }

  async function publish() {
    if (!entry) return;
    setPublishing(false);
    try {
      const published = await publishPlugin(entry.id);
      toast.success(t("publish.done", { name: published.name }));
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("publish.failed"));
    }
  }

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
        stackActionsOnMobile
        actions={[
          <Button
            key="back"
            prominence="secondary"
            icon={SvgArrowLeft}
            {...navigation.linkTo("/app/plugins")}
          >
            {t("back.label")}
          </Button>,
          ...(owner
            ? [
                <Button
                  key="share"
                  prominence="secondary"
                  icon={SvgShare}
                  onClick={() => setSharing(true)}
                >
                  {t("share.label")}
                </Button>,
                <Button
                  key="publish"
                  prominence="secondary"
                  icon={SvgOrganization}
                  disabled={!isActionManager}
                  tooltip={isActionManager ? undefined : t("publish.blocked")}
                  onClick={() => setPublishing(true)}
                >
                  {t("publish.label")}
                </Button>,
              ]
            : []),
          ...(pending > 0
            ? [
                <Badge
                  key="pending"
                  size={6}
                  color="warning"
                  title={promptCopy("trigger.label", { count: pending })}
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
              <OverviewTab entry={entry} onChanged={refresh} />
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
      {entry && sharing && (
        <SharePluginModal
          pluginId={entry.id}
          pluginName={entry.name}
          sharedSignIn={entry.integrations
            .filter((integration) => integration.auth_mode === "shared")
            .map((integration) => integration.name)}
          onClose={() => setSharing(false)}
          onSaved={() => setSharing(false)}
        />
      )}
      {entry && publishing && (
        <GenericConfirmModal
          title={t("publish.confirmTitle", { name: entry.name })}
          message={t("publish.confirmMessage")}
          confirmText={t("publish.label")}
          onClose={() => setPublishing(false)}
          onConfirm={() => void publish()}
        />
      )}
    </SettingsLayouts.Root>
  );
}
