"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Badge, Button, Card, InputSwitch } from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import { SvgBlocks, SvgOrganization, SvgShare } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import { publishPlugin, setPluginEnabled } from "@/lib/integrations/svc";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  memberPluginEntries,
  ownsPrivateIntegrationPlugin,
  pendingIntegrations,
  pluginSwitch,
  type MemberPluginEntry,
} from "@/lib/plugins/directory";
import {
  customizeTabHref,
  parsePluginPageTab,
  pluginHref,
  skillHref,
  type PluginPageTab,
} from "@/lib/customize/paths";
import { setSkillEnabled } from "@/lib/skills/api";
import { canChangeOrganizationAccess } from "@/lib/skills/sharing";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import AlwaysAllowList from "@/sections/plugins/AlwaysAllowList";
import IntegrationConnectionRow from "@/sections/plugins/IntegrationConnectionRow";
import SharePluginModal from "@/sections/plugins/SharePluginModal";
import GenericConfirmModal from "@/sections/modals/GenericConfirmModal";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";
import CustomizeDetailLayout, {
  BackLink,
  DetailOverview,
  type DetailTab,
} from "@/sections/customize/CustomizeDetailLayout";

interface PluginTabProps {
  entry: MemberPluginEntry;
}

interface OverviewTabProps extends PluginTabProps {
  onChanged: () => Promise<void>;
}

function PluginSwitch({ entry, onChanged }: OverviewTabProps) {
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
    <Section width="auto" height="auto" padding={1}>
      <InputSwitch
        aria-label={t("label", { name: entry.name })}
        checked={enabled}
        disabled={busy || blocked !== null}
        onCheckedChange={(checked) => void change(checked)}
      />
    </Section>
  );
}

function OverviewTab({ entry }: PluginTabProps) {
  const t = useTranslations("plugins.member.detail.overview");
  const switchCopy = useTranslations("plugins.member.detail.switch");
  const sections = useTranslations("plugins.member.sections");
  const { blocked } = pluginSwitch(entry);
  return (
    <DetailOverview
      descriptionLabel={t("description")}
      description={entry.description ?? t("noDescription")}
      facts={[
        {
          label: switchCopy("title"),
          value: blocked ? switchCopy(blocked) : switchCopy("description"),
        },
        { label: t("location"), value: sections(entry.section) },
        ...(entry.ownerEmail
          ? [{ label: t("owner"), value: entry.ownerEmail }]
          : []),
        ...(entry.skills.length > 0
          ? [
              {
                label: t("skills"),
                value: entry.skills.map((skill) => skill.name).join(", "),
              },
            ]
          : []),
        ...(entry.integrations.length > 0
          ? [
              {
                label: t("integrations"),
                value: entry.integrations
                  .map((integration) => integration.name)
                  .join(", "),
              },
            ]
          : []),
      ]}
    />
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
  const returnPath = pluginHref(entry.id, "integrations");
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
  const tabCopy = useTranslations("customize.tabs");
  const pageCopy = useTranslations("customize.pluginPage");
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
  const skillOnlyId =
    skills.data &&
    integrations.data &&
    entry !== undefined &&
    entry.skills.length === 1 &&
    entry.integrations.length === 0
      ? entry.skills[0]?.id
      : undefined;
  useEffect(() => {
    if (skillOnlyId) navigation.go(skillHref(skillOnlyId), { replace: true });
  }, [navigation, skillOnlyId]);
  const skill = entry?.skills.length === 1 ? entry.skills[0] : undefined;
  const showVersions =
    skill !== undefined &&
    (skill.user_permission === "OWNER" || skill.user_permission === "EDITOR");
  const available: PluginPageTab[] = [
    "overview",
    ...(entry && entry.skills.length > 0 ? (["skills"] as const) : []),
    ...(entry && entry.integrations.length > 0
      ? (["integrations"] as const)
      : []),
    ...(showVersions ? (["versions"] as const) : []),
  ];
  const requested = parsePluginPageTab(searchParams.get("tab"));
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
      toast.success(t("publish.done", { name: published?.name ?? entry.name }));
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("publish.failed"));
    }
  }

  const tabs: DetailTab<PluginPageTab>[] | null = entry
    ? [
        {
          value: "overview",
          label: t("tabs.overview"),
          content: <OverviewTab entry={entry} />,
        },
        ...(entry.skills.length > 0
          ? [
              {
                value: "skills" as const,
                label: pageCopy("tabs.skills", { count: entry.skills.length }),
                content: <SkillsTab entry={entry} />,
              },
            ]
          : []),
        ...(entry.integrations.length > 0
          ? [
              {
                value: "integrations" as const,
                label: pageCopy("tabs.integrations", {
                  count: entry.integrations.length,
                }),
                content: <IntegrationsTab entry={entry} />,
              },
            ]
          : []),
        ...(skill && showVersions
          ? [
              {
                value: "versions" as const,
                label: t("tabs.versions"),
                content: (
                  <SkillVersionsTab
                    skill={skill}
                    canPublish={canChangeOrganizationAccess(
                      skill,
                      isGlobalHolder
                    )}
                    onChanged={() => void skills.refresh()}
                  />
                ),
              },
            ]
          : []),
      ]
    : null;

  return (
    <CustomizeDetailLayout
      back={
        <BackLink to={customizeTabHref("plugins")} label={tabCopy("plugins")} />
      }
      icon={SvgBlocks}
      title={entry?.name ?? t("title")}
      description={entry?.description ?? undefined}
      loading={loading || skillOnlyId !== undefined}
      error={
        loading
          ? false
          : skills.error || integrations.error
            ? t("loadFailed")
            : entry
              ? false
              : t("notFound")
      }
      tabs={tabs}
      tab={tab}
      onTabChange={(next) =>
        navigation.go(pluginHref(pluginId, next), {
          replace: true,
          scroll: false,
        })
      }
      actions={[
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
        ...(entry
          ? [<PluginSwitch key="switch" entry={entry} onChanged={refresh} />]
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
    >
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
    </CustomizeDetailLayout>
  );
}
