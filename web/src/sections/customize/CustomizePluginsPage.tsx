"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  InputTypeIn,
  LineItemButton,
  Text,
  type DropdownMenuItem,
} from "@opal/components";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  ContentAction,
  Section,
  SettingsLayouts,
  Toolbar,
} from "@opal/layouts";
import {
  SvgCheckCircle,
  SvgPlug,
  SvgPlus,
  SvgShare,
  SvgUploadCloud,
  SvgXCircle,
} from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { useNavigation } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import {
  PLUGIN_GROUPS,
  groupPlugins,
  type PluginGroup,
} from "@/lib/customize/plugins";
import { usePanel } from "@/lib/customize/hooks";
import { pluginHref } from "@/lib/customize/paths";
import type { SkillStatusFilter } from "@/lib/customize/skills";
import {
  memberPluginEntries,
  pluginSwitch,
  type MemberPluginEntry,
} from "@/lib/plugins/directory";
import {
  useSkillEnablement,
  type SkillEnablement,
  useRefreshSkillLists,
} from "@/lib/skills/hooks";
import { useMarketplaceAdded, useMarketplaces } from "@/lib/marketplaces/hooks";
import { needsAttention } from "@/lib/plugins/needs";
import { canShareSkill } from "@/lib/skills/sharing";
import type { Skill } from "@/lib/skills/types";
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
import AddMarketplaceModal from "@/sections/marketplaces/AddMarketplaceModal";
import MarketplacesTable from "@/sections/marketplaces/MarketplacesTable";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import SkillSwitchModal from "@/sections/modals/skills/SkillSwitchModal";
import PluginTurnOnModal from "@/sections/modals/plugins/PluginTurnOnModal";
import UploadPluginFlow from "@/sections/modals/plugins/UploadPluginFlow";

interface PluginRowProps {
  entry: MemberPluginEntry;
  group: PluginGroup;
  enablement: SkillEnablement;
  onSwitch: (entry: MemberPluginEntry, enabled: boolean) => void;
  onShare: (entry: MemberPluginEntry) => void;
}

function PluginRow({
  entry,
  group,
  enablement,
  onSwitch,
  onShare,
}: PluginRowProps) {
  const t = useTranslations("customize");
  const navigation = useNavigation();
  const panel = usePanel();
  const [skill] = entry.skills;
  const { blocked } = pluginSwitch(entry);
  const enabled = skill ? enablement.enabledOf(skill) : false;
  const busy = skill ? enablement.isPending(skill.id) : false;
  const canToggle = blocked === null;
  const canShare = skill !== undefined && canShareSkill(skill);
  const source =
    entry.marketplace !== null
      ? t("skills.source.marketplace", {
          name: entry.marketplace.name,
          scope: entry.marketplace.personal ? "personal" : "company",
        })
      : group === "mine"
        ? t("skills.source.mine")
        : group === "organization"
          ? t("skills.source.organization")
          : group === "private" && entry.ownerEmail
            ? t("skills.source.privateTo", { email: entry.ownerEmail })
            : entry.ownerEmail
              ? t("skills.source.sharedBy", { email: entry.ownerEmail })
              : t("skills.source.shared");
  const heldBy = skill?.name_held_by ?? [];
  const contents =
    !enabled && heldBy.length > 0
      ? t("plugins.nameHeld", { names: heldBy.join(", ") })
      : skill && skill.needed_count > 0
        ? t("plugins.integrations", {
            available: skill.available_count,
            needed: skill.needed_count,
          })
        : (entry.description ?? "");
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
      icon={skill ? skillIcon(skill) : undefined}
      title={entry.name}
      titleMaxLines={1}
      description={
        contents
          ? t("skills.subtitle", { source, description: contents })
          : source
      }
      descriptionMaxLines={1}
      badge={
        !enabled
          ? { title: t("skills.tag.off") }
          : blocked === "required"
            ? { title: t("skills.tag.required"), color: "info" }
            : undefined
      }
      aria-label={t("skills.open", { name: entry.name })}
      onClick={() => navigation.go(pluginHref(entry.id, undefined, panel))}
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

/** The admin panel lists every plugin the admin sees, in admin chrome.
 * Both panels list marketplaces below the plugins once one exists. */
export default function CustomizePluginsPage() {
  const t = useTranslations("customize");
  const panel = usePanel();
  const adminCopy = useTranslations("admin.plugins");
  const marketplaceCopy = useTranslations("plugins.marketplaces");
  const onMarketplaceAdded = useMarketplaceAdded();
  const marketplaceList = useMarketplaces();
  const showMarketplaces =
    (marketplaceList.marketplaces?.length ?? 0) > 0 ||
    marketplaceList.error !== undefined;
  const locale = useLocale();
  const { user } = useUser();
  const revalidate = useRefreshSkillLists();
  const skills = useUserSkills();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<SkillStatusFilter>("all");
  const [sharing, setSharing] = useState<MemberPluginEntry | null>(null);
  const [turnedOn, setTurnedOn] = useState<Skill | null>(null);
  const [uploading, setUploading] = useState(false);
  const [addingMarketplace, setAddingMarketplace] = useState(false);

  const userEmail = user?.email ?? null;
  const entries = memberPluginEntries(
    (skills.data?.customs ?? []).filter(
      (skill) =>
        skill.kind === "plugin" && (panel === "admin" || skill.member_visible)
    ),
    userEmail,
    locale
  );
  const enablement = useSkillEnablement(
    skills.data?.customs ?? [],
    skills.refresh,
    (skill) => {
      if (needsAttention(skill.plugin?.needs ?? [])) setTurnedOn(skill);
    }
  );
  const groups = groupPlugins(entries, { userEmail, query, status, locale });
  const shownCount = PLUGIN_GROUPS.reduce(
    (count, group) => count + groups[group].length,
    0
  );

  const statusFilter = (
    <StatusFilter
      value={status}
      onChange={setStatus}
      allLabel={t("plugins.filter.all")}
    />
  );
  const addMenu = <AddSkillMenu key="add" upload="plugin" />;
  const loadError = skills.error ? t("plugins.loadFailed") : false;

  const marketplaces = (
    <>
      {showMarketplaces && (
        <Section id="marketplaces" gap={1} alignItems="stretch" height="auto">
          <ContentAction
            font="main-content-emphasis"
            icon={SvgGitHub}
            title={marketplaceCopy("page.title")}
            description={marketplaceCopy("page.description")}
            padding={0}
            rightChildren={
              <Button
                prominence="secondary"
                icon={SvgPlus}
                onClick={() => setAddingMarketplace(true)}
              >
                {marketplaceCopy("add.menuItem")}
              </Button>
            }
          />
          <MarketplacesTable />
        </Section>
      )}
      <AddMarketplaceModal
        open={addingMarketplace}
        onClose={() => setAddingMarketplace(false)}
        onAdded={(marketplace) => {
          setAddingMarketplace(false);
          onMarketplaceAdded(marketplace);
        }}
      />
    </>
  );

  const list = (
    <>
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
            entries.length > 0 ? (
              <Button
                prominence="secondary"
                onClick={() => {
                  setQuery("");
                  setStatus("all");
                }}
              >
                {t("plugins.noMatches.clear")}
              </Button>
            ) : (
              <Section
                flexDirection="row"
                justifyContent="center"
                gap={2}
                height="auto"
                wrap
              >
                <Button
                  icon={SvgUploadCloud}
                  onClick={() => setUploading(true)}
                >
                  {t("plugins.empty.upload")}
                </Button>
                {!showMarketplaces && (
                  <Button
                    prominence="secondary"
                    icon={SvgGitHub}
                    onClick={() => setAddingMarketplace(true)}
                  >
                    {marketplaceCopy("add.menuItem")}
                  </Button>
                )}
              </Section>
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
                enablement={enablement}
                onSwitch={(target, enabled) => {
                  const [skill] = target.skills;
                  if (skill) void enablement.setEnabled(skill, enabled);
                }}
                onShare={setSharing}
              />
            ))}
          </CustomizeGroup>
        ))
      )}

      <SkillSwitchModal enablement={enablement} />
      <UploadPluginFlow open={uploading} onClose={() => setUploading(false)} />
      {turnedOn && (
        <PluginTurnOnModal
          plugin={turnedOn}
          onClose={() => setTurnedOn(null)}
        />
      )}
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
    </>
  );

  if (panel === "admin")
    return (
      <SettingsLayouts.Root
        width="lg"
        loading={skills.isLoading}
        error={loadError}
      >
        <SettingsLayouts.Header
          icon={SvgPlug}
          title={adminCopy("title")}
          description={adminCopy("description")}
          stackActionsOnMobile
          actions={[addMenu]}
        />
        <SettingsLayouts.Body>
          <Toolbar
            search={
              <InputTypeIn
                icon="search"
                value={query}
                placeholder={t("search")}
                aria-label={t("search")}
                onChange={(event) => setQuery(event.target.value)}
              />
            }
            actions={statusFilter}
          />
          {list}
          {marketplaces}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );

  return (
    <CustomizeLayout
      tab="plugins"
      query={query}
      onQueryChange={setQuery}
      controls={
        <>
          {statusFilter}
          {addMenu}
        </>
      }
      loading={skills.isLoading}
      error={loadError}
    >
      <Text as="p" font="secondary-body" color="text-03">
        {t("plugins.intro")}
      </Text>
      {list}
      {marketplaces}
    </CustomizeLayout>
  );
}
