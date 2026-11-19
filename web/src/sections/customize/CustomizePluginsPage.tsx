"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  LineItemButton,
  Text,
  type DropdownMenuItem,
} from "@opal/components";
import { toast } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgBlocks,
  SvgCheckCircle,
  SvgPlug,
  SvgShare,
  SvgXCircle,
} from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import type { IconFunctionComponent } from "@opal/types";
import useUserSkills from "@/hooks/useUserSkills";
import {
  PLUGIN_GROUPS,
  groupPlugins,
  type PluginGroup,
} from "@/lib/customize/plugins";
import { NEW_INTEGRATION_PATH, pluginHref } from "@/lib/customize/paths";
import type { SkillStatusFilter } from "@/lib/customize/skills";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import { setPluginEnabled } from "@/lib/integrations/svc";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  memberPluginEntries,
  ownsPrivateIntegrationPlugin,
  pendingIntegrations,
  pluginSwitch,
  type MemberPluginEntry,
} from "@/lib/plugins/directory";
import {
  useSkillEnablement,
  type SkillEnablement,
  useRefreshSkillLists,
} from "@/lib/skills/hooks";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import CustomizeLayout from "@/sections/customize/CustomizeLayout";
import AddSkillMenu from "@/sections/customize/AddSkillMenu";
import {
  CustomizeEmpty,
  CustomizeGroup,
  CustomizeRowActions,
  StatusFilter,
} from "@/sections/customize/CustomizeList";
import { skillIcon } from "@/sections/customize/skillIcon";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import SkillSwitchModal from "@/sections/modals/skills/SkillSwitchModal";
import SharePluginModal from "@/sections/plugins/SharePluginModal";

function pluginIcon(entry: MemberPluginEntry): IconFunctionComponent {
  const [skill] = entry.skills;
  if (skill && entry.integrations.length === 0) return skillIcon(skill);
  return entry.skills.length === 0 ? SvgPlug : SvgBlocks;
}

interface PluginRowProps {
  entry: MemberPluginEntry;
  group: PluginGroup;
  userEmail: string | null;
  enablement: SkillEnablement;
  onSwitch: (entry: MemberPluginEntry, enabled: boolean) => void;
  switching: boolean;
  onShare: (entry: MemberPluginEntry) => void;
}

function PluginRow({
  entry,
  group,
  userEmail,
  enablement,
  onSwitch,
  switching,
  onShare,
}: PluginRowProps) {
  const t = useTranslations("customize");
  const navigation = useNavigation();
  const [skill] = entry.skills;
  const { blocked } = pluginSwitch(entry);
  const enabled = skill
    ? enablement.enabledOf(skill)
    : pluginSwitch(entry).enabled;
  const busy = switching || (skill ? enablement.isPending(skill.id) : false);
  const canToggle = blocked === null;
  const pending = pendingIntegrations(entry.integrations).length;
  const canShare =
    ownsPrivateIntegrationPlugin(entry, userEmail) ||
    (skill !== undefined &&
      (skill.user_permission === "OWNER" ||
        skill.user_permission === "EDITOR"));
  const source =
    group === "mine"
      ? t("skills.source.mine")
      : group === "organization"
        ? t("skills.source.organization")
        : entry.ownerEmail
          ? t("skills.source.sharedBy", { email: entry.ownerEmail })
          : t("skills.source.shared");
  const contents = t("plugins.contents", {
    skills: entry.skills.length,
    integrations: entry.integrations.length,
    both:
      entry.skills.length > 0 && entry.integrations.length > 0 ? "yes" : "no",
  });
  const menu: DropdownMenuItem[] = [
    ...(canToggle
      ? [
          {
            kind: "action" as const,
            id: "toggle",
            icon: enabled ? SvgXCircle : SvgCheckCircle,
            title: enabled ? t("skills.menu.turnOff") : t("skills.menu.turnOn"),
            disabled: busy,
            onSelect: () => onSwitch(entry, !enabled),
          },
        ]
      : []),
    ...(canShare
      ? [
          {
            kind: "action" as const,
            id: "share",
            icon: SvgShare,
            title: t("skills.menu.share"),
            onSelect: () => onShare(entry),
          },
        ]
      : []),
  ];
  return (
    <LineItemButton
      icon={pluginIcon(entry)}
      title={entry.name}
      titleMaxLines={1}
      description={t("skills.subtitle", { source, description: contents })}
      descriptionMaxLines={1}
      badge={
        !enabled
          ? { title: t("skills.tag.off") }
          : pending > 0
            ? {
                title: t("plugins.needsSignIn", { count: pending }),
                color: "warning",
              }
            : blocked === "required"
              ? { title: t("skills.tag.required"), color: "info" }
              : undefined
      }
      aria-label={t("skills.open", { name: entry.name })}
      onClick={() => navigation.go(pluginHref(entry.id))}
      rightChildren={
        <CustomizeRowActions
          turnOn={
            !enabled && canToggle
              ? {
                  label: t("skills.menu.turnOn"),
                  disabled: busy,
                  onClick: () => onSwitch(entry, true),
                }
              : undefined
          }
          menuLabel={t("skills.menu.label", { name: entry.name })}
          menu={menu}
        />
      }
    />
  );
}

export default function CustomizePluginsPage() {
  const t = useTranslations("customize");
  const locale = useLocale();
  const navigation = useNavigation();
  const { user } = useUser();
  const revalidate = useRefreshSkillLists();
  const skills = useUserSkills();
  const integrations = useMemberIntegrations();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canAddIntegration = isGlobalHolder || isScopedManager;
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<SkillStatusFilter>("all");
  const [switching, setSwitching] = useState<ReadonlySet<string>>(new Set());
  const [sharing, setSharing] = useState<MemberPluginEntry | null>(null);

  const userEmail = user?.email ?? null;
  const entries = memberPluginEntries(
    skills.data?.customs ?? [],
    integrations.data ?? [],
    userEmail,
    locale
  );
  const enablement = useSkillEnablement(
    skills.data?.customs ?? [],
    skills.refresh
  );
  const groups = groupPlugins(entries, { userEmail, query, status, locale });
  const shownCount = PLUGIN_GROUPS.reduce(
    (count, group) => count + groups[group].length,
    0
  );
  const loading = skills.isLoading || integrations.isLoading;

  async function switchPlugin(
    entry: MemberPluginEntry,
    enabled: boolean
  ): Promise<void> {
    const [skill] = entry.skills;
    if (skill) {
      await enablement.setEnabled(skill, enabled);
      return;
    }
    setSwitching((current) => new Set([...current, entry.id]));
    try {
      await setPluginEnabled(entry.id, enabled);
      await integrations.mutate();
    } catch (failure) {
      toast.error(
        failure instanceof Error ? failure.message : t("plugins.switchFailed")
      );
    } finally {
      setSwitching((current) => {
        const next = new Set(current);
        next.delete(entry.id);
        return next;
      });
    }
  }

  const controls = (
    <>
      <StatusFilter
        value={status}
        onChange={setStatus}
        allLabel={t("plugins.filter.all")}
      />
      <AddSkillMenu
        extraItems={
          canAddIntegration
            ? [
                {
                  kind: "action",
                  id: "integration",
                  icon: SvgPlug,
                  title: t("integrations.add.integration"),
                  onSelect: () => navigation.go(NEW_INTEGRATION_PATH),
                },
              ]
            : []
        }
      />
    </>
  );

  return (
    <CustomizeLayout
      tab="plugins"
      query={query}
      onQueryChange={setQuery}
      controls={controls}
      loading={loading}
      error={
        skills.error || integrations.error ? t("plugins.loadFailed") : false
      }
    >
      <Text as="p" font="secondary-body" color="text-03">
        {t("plugins.intro")}
      </Text>
      {shownCount === 0 ? (
        <CustomizeEmpty
          illustration={SvgNoResult}
          title={
            entries.length > 0
              ? t("plugins.noMatches.title")
              : t("plugins.empty.title")
          }
          description={
            entries.length > 0
              ? t("skills.noMatches.description")
              : t("plugins.empty.description")
          }
          action={
            entries.length > 0 && (
              <Button
                prominence="secondary"
                onClick={() => {
                  setQuery("");
                  setStatus("all");
                }}
              >
                {t("plugins.noMatches.clear")}
              </Button>
            )
          }
        />
      ) : (
        PLUGIN_GROUPS.map((group) => (
          <CustomizeGroup key={group} title={t(`skills.groups.${group}`)}>
            {groups[group].map((entry) => (
              <PluginRow
                key={entry.id}
                entry={entry}
                group={group}
                userEmail={userEmail}
                enablement={enablement}
                switching={switching.has(entry.id)}
                onSwitch={(target, enabled) =>
                  void switchPlugin(target, enabled)
                }
                onShare={setSharing}
              />
            ))}
          </CustomizeGroup>
        ))
      )}

      <SkillSwitchModal enablement={enablement} />
      {sharing && sharing.skills[0] && (
        <ShareSkillModal
          mode="edit"
          skillId={sharing.skills[0].id}
          fallbackTitle={sharing.name}
          open
          onClose={() => setSharing(null)}
          onSaved={revalidate}
        />
      )}
      {sharing && sharing.skills.length === 0 && (
        <SharePluginModal
          pluginId={sharing.id}
          pluginName={sharing.name}
          sharedSignIn={sharing.integrations
            .filter((integration) => integration.auth_mode === "shared")
            .map((integration) => integration.name)}
          onClose={() => setSharing(null)}
          onSaved={() => setSharing(null)}
        />
      )}
    </CustomizeLayout>
  );
}
