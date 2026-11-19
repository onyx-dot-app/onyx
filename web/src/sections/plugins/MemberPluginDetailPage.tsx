"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Card, InputSwitch, Text } from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import { SvgBlocks } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  memberPluginEntries,
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
import { usePluginDetail } from "@/lib/plugins/hooks";
import { needsAttention } from "@/lib/plugins/needs";
import type { PluginDetail } from "@/lib/plugins/types";
import { setSkillEnabled } from "@/lib/skills/api";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import type { Skill } from "@/lib/skills/types";
import { canChangeOrganizationAccess } from "@/lib/skills/sharing";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";
import PluginTurnOnModal from "@/sections/modals/plugins/PluginTurnOnModal";
import PluginNeedList from "@/sections/plugins/PluginNeedList";
import CustomizeDetailLayout, {
  BackLink,
  DetailOverview,
  type DetailTab,
} from "@/sections/customize/CustomizeDetailLayout";

interface PluginTabProps {
  entry: MemberPluginEntry;
}

interface PluginSwitchProps extends PluginTabProps {
  onChanged: () => Promise<void>;
  /** Called with the plugin after a turn on that left a need not on. */
  onNeedsAttention: (plugin: Skill) => void;
}

function PluginSwitch({
  entry,
  onChanged,
  onNeedsAttention,
}: PluginSwitchProps) {
  const t = useTranslations("plugins.member.detail.switch");
  const [busy, setBusy] = useState(false);
  const { enabled, blocked } = pluginSwitch(entry);
  const skill = entry.skills[0];

  async function change(next: boolean) {
    setBusy(true);
    if (!skill) return;
    try {
      const updated = await setSkillEnabled(skill.id, next);
      await onChanged();
      if (next && needsAttention(updated.plugin?.needs ?? []))
        onNeedsAttention(updated);
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

interface OverviewTabProps extends PluginTabProps {
  plugin: PluginDetail | null;
}

function OverviewTab({ entry, plugin }: OverviewTabProps) {
  const t = useTranslations("plugins.member.detail.overview");
  const switchCopy = useTranslations("plugins.member.detail.switch");
  const sections = useTranslations("plugins.member.sections");
  const unusedCopy = useTranslations("plugins.upload.unusedParts");
  const { blocked } = pluginSwitch(entry);
  const manifest = plugin?.manifest ?? null;
  const skillNames = plugin
    ? plugin.skills.map((skill) => skill.name)
    : entry.skills.map((skill) => skill.name);
  const author = manifest?.author?.name ?? manifest?.author?.email ?? null;
  const link = manifest?.homepage ?? manifest?.repository ?? null;
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
        ...(manifest?.version
          ? [{ label: t("version"), value: manifest.version }]
          : []),
        ...(author ? [{ label: t("author"), value: author }] : []),
        ...(link ? [{ label: t("homepage"), value: link, mono: true }] : []),
        ...(manifest?.license
          ? [{ label: t("license"), value: manifest.license }]
          : []),
        ...(skillNames.length > 0
          ? [{ label: t("skills"), value: skillNames.join(", ") }]
          : []),
        ...(manifest && manifest.unused_parts.length > 0
          ? [
              {
                label: t("notUsed"),
                value: manifest.unused_parts
                  .map((part) => unusedCopy(part))
                  .join(", "),
              },
            ]
          : []),
      ]}
    />
  );
}

function SkillsTab({ entry, plugin }: OverviewTabProps) {
  const t = useTranslations("plugins.member.detail.skills");
  if (plugin)
    return (
      <Section gap={2} alignItems="stretch" height="auto">
        {plugin.skills.map((skill) => (
          <Card key={skill.path} padding={4}>
            <Content title={skill.name} description={skill.description} />
          </Card>
        ))}
      </Section>
    );
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
  plugin: PluginDetail;
  onChanged: () => void;
}

function IntegrationsTab({ plugin, onChanged }: IntegrationsTabProps) {
  const t = useTranslations("plugins.needs");
  return (
    <Section gap={2} alignItems="stretch" height="auto">
      <Text as="p" font="secondary-body" color="text-03">
        {t("intro")}
      </Text>
      <PluginNeedList needs={plugin.needs} interactive onChanged={onChanged} />
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
  const tabCopy = useTranslations("customize.tabs");
  const pageCopy = useTranslations("customize.pluginPage");
  const locale = useLocale();
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const { user } = useUser();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const skills = useUserSkills();
  const entry = memberPluginEntries(
    skills.data?.customs ?? [],
    user?.email ?? null,
    locale
  ).find((candidate) => candidate.id === pluginId);
  const isPlugin = entry?.skills[0]?.kind === "plugin";
  const detail = usePluginDetail(isPlugin ? pluginId : null);
  const plugin = isPlugin ? (detail.data?.plugin ?? null) : null;
  const refreshLists = useRefreshSkillLists();
  const [turnedOn, setTurnedOn] = useState<Skill | null>(null);
  const loading =
    skills.isLoading || (isPlugin && plugin === null && !detail.error);
  const skillOnlyId =
    skills.data && entry !== undefined && !isPlugin && entry.skills.length === 1
      ? entry.skills[0]?.id
      : undefined;
  useEffect(() => {
    if (skillOnlyId) navigation.go(skillHref(skillOnlyId), { replace: true });
  }, [navigation, skillOnlyId]);
  const skill = entry?.skills.length === 1 ? entry.skills[0] : undefined;
  const showVersions =
    skill !== undefined &&
    (skill.user_permission === "OWNER" || skill.user_permission === "EDITOR");
  const skillCount = plugin
    ? plugin.skills.length
    : (entry?.skills.length ?? 0);
  const needCount = plugin?.needs.length ?? 0;
  const available: PluginPageTab[] = [
    "overview",
    ...(skillCount > 0 ? (["skills"] as const) : []),
    ...(needCount > 0 ? (["integrations"] as const) : []),
    ...(showVersions ? (["versions"] as const) : []),
  ];
  const requested = parsePluginPageTab(searchParams.get("tab"));
  const tab = available.includes(requested) ? requested : "overview";

  async function refresh(): Promise<void> {
    await Promise.all([skills.refresh(), isPlugin ? detail.refresh() : null]);
  }

  const tabs: DetailTab<PluginPageTab>[] | null = entry
    ? [
        {
          value: "overview",
          label: t("tabs.overview"),
          content: <OverviewTab entry={entry} plugin={plugin} />,
        },
        ...(skillCount > 0
          ? [
              {
                value: "skills" as const,
                label: pageCopy("tabs.skills", { count: skillCount }),
                content: <SkillsTab entry={entry} plugin={plugin} />,
              },
            ]
          : []),
        ...(plugin && needCount > 0
          ? [
              {
                value: "integrations" as const,
                label: pageCopy("tabs.integrations", { count: needCount }),
                content: (
                  <IntegrationsTab
                    plugin={plugin}
                    onChanged={() => {
                      void detail.refresh();
                      refreshLists();
                    }}
                  />
                ),
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
                    onChanged={() => void refresh()}
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
          : skills.error || detail.error
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
      actions={
        entry
          ? [
              <PluginSwitch
                key="switch"
                entry={entry}
                onChanged={refresh}
                onNeedsAttention={setTurnedOn}
              />,
            ]
          : undefined
      }
    >
      {turnedOn && (
        <PluginTurnOnModal
          plugin={turnedOn}
          onClose={() => setTurnedOn(null)}
        />
      )}
    </CustomizeDetailLayout>
  );
}
