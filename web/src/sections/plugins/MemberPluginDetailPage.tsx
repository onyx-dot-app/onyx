"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  InputSwitch,
  MessageCard,
  Modal,
  Text,
  useCreateModal,
  type DropdownMenuItem,
} from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import {
  SvgBlocks,
  SvgFileText,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
  SvgUploadCloud,
} from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { useNavigation, useSearchParams } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  memberPluginEntries,
  pluginSwitch,
  type MemberPluginEntry,
} from "@/lib/plugins/directory";
import {
  MARKETPLACES_PATH,
  customizeTabHref,
  parsePluginPageTab,
  pluginHref,
  skillHref,
  type PluginPageTab,
} from "@/lib/customize/paths";
import { usePluginDetail } from "@/lib/plugins/hooks";
import { needsAttention } from "@/lib/plugins/needs";
import type { PluginDetail, PluginSkillSummary } from "@/lib/plugins/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { deleteUserSkill } from "@/lib/skills/api";
import {
  useRefreshSkillLists,
  useSkillEnablement,
  type SkillEnablement,
} from "@/lib/skills/hooks";
import type { Skill } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  canChangeOrganizationAccess,
  canShareSkill,
} from "@/lib/skills/sharing";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import { SkillInstructionsPanel } from "@/sections/modals/SkillPreviewModal";
import UploadPluginFlow from "@/sections/modals/plugins/UploadPluginFlow";
import SkillSwitchModal from "@/sections/modals/skills/SkillSwitchModal";
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
  enablement: SkillEnablement;
}

function PluginSwitch({ entry, enablement }: PluginSwitchProps) {
  const t = useTranslations("plugins.member.detail.switch");
  const { blocked } = pluginSwitch(entry);
  const skill = entry.skills[0];

  return (
    <Section flexDirection="row" width="auto" height="auto" gap={1} padding={1}>
      <Text font="main-ui-body" color="text-03">
        {t("title")}
      </Text>
      <InputSwitch
        aria-label={t("label", { name: entry.name })}
        checked={skill ? enablement.enabledOf(skill) : false}
        disabled={!skill || enablement.isPending(skill.id) || blocked !== null}
        onCheckedChange={(checked) => {
          if (skill) void enablement.setEnabled(skill, checked);
        }}
      />
    </Section>
  );
}

interface OverviewTabProps extends PluginTabProps {
  plugin: PluginDetail | null;
  enablement: SkillEnablement;
}

interface ManagedNoteProps {
  marketplace: NonNullable<MemberPluginEntry["marketplace"]>;
}

/** Why a synced plugin has no edit, upload or delete: GitHub holds its files. */
function ManagedNote({ marketplace }: ManagedNoteProps) {
  const t = useTranslations("plugins.member.detail.managed");
  const navigation = useNavigation();
  return (
    <MessageCard
      variant="info"
      outerPadding={1}
      innerPadding={1}
      title={t("title", { name: marketplace.name })}
      description={t("description", {
        repository: marketplace.repository ?? marketplace.name,
      })}
      rightChildren={
        <Button
          prominence="secondary"
          size="sm"
          {...navigation.linkTo(MARKETPLACES_PATH)}
        >
          {t("open")}
        </Button>
      }
    />
  );
}

function OverviewTab({ entry, plugin, enablement }: OverviewTabProps) {
  const t = useTranslations("plugins.member.detail.overview");
  const switchCopy = useTranslations("plugins.member.detail.switch");
  const sections = useTranslations("plugins.member.sections");
  const unusedCopy = useTranslations("plugins.upload.unusedParts");
  const { blocked } = pluginSwitch(entry);
  const skill = entry.skills[0];
  const heldBy = skill?.name_held_by ?? [];
  const enabled = skill ? enablement.enabledOf(skill) : false;
  const manifest = plugin?.manifest ?? null;
  const skillNames = plugin
    ? plugin.skills.map((item) => item.name)
    : entry.skills.map((item) => item.name);
  const author = manifest?.author?.name ?? manifest?.author?.email ?? null;
  const link = manifest?.homepage ?? manifest?.repository ?? null;
  const location = entry.marketplace
    ? t("marketplace", {
        name: entry.marketplace.name,
        scope: entry.marketplace.personal ? "personal" : "company",
        repository: entry.marketplace.repository ?? "",
      })
    : sections(entry.section);
  return (
    <Section gap={2} alignItems="stretch" height="auto">
      {entry.marketplace && <ManagedNote marketplace={entry.marketplace} />}
      <DetailOverview
        descriptionLabel={t("description")}
        description={entry.description ?? t("noDescription")}
        facts={[
          {
            label: switchCopy("title"),
            value: blocked
              ? switchCopy(blocked)
              : heldBy.length > 0
                ? switchCopy("nameHeld", { names: heldBy.join(", ") })
                : enabled
                  ? switchCopy("on")
                  : switchCopy("off"),
          },
          { label: t("location"), value: location },
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
    </Section>
  );
}

interface PluginSkillModalProps {
  pluginId: string;
  skill: PluginSkillSummary;
  onClose: () => void;
}

/** The SKILL.md instructions of one skill in the plugin. */
function PluginSkillModal({ pluginId, skill, onClose }: PluginSkillModalProps) {
  const t = useTranslations("plugins.member.detail.skills");
  const { data, error, isLoading } = useSWR<{ instructions_markdown: string }>(
    SWR_KEYS.pluginSkill(pluginId, skill.path),
    errorHandlingFetcher
  );
  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="lg" maxHeight="85dvh">
        <Modal.Header
          icon={SvgFileText}
          title={skill.name}
          description={skill.description}
          onClose={onClose}
        />
        <Modal.Body>
          {isLoading ? (
            <IconLoader />
          ) : error || !data ? (
            <MessageCard variant="error" title={t("readFailed")} />
          ) : (
            <SkillInstructionsPanel
              instructionsMarkdown={
                data.instructions_markdown || t("noInstructions")
              }
            />
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

function SkillsTab({ entry, plugin }: Omit<OverviewTabProps, "enablement">) {
  const t = useTranslations("plugins.member.detail.skills");
  const [reading, setReading] = useState<PluginSkillSummary | null>(null);
  if (plugin)
    return (
      <Section gap={2} alignItems="stretch" height="auto">
        {plugin.skills.map((skill) => (
          <Card key={skill.path} padding={2}>
            <ContentAction
              title={skill.name}
              description={skill.description}
              padding={1}
              responsive
              rightChildren={
                <Button
                  prominence="secondary"
                  icon={SvgFileText}
                  aria-label={t("readAriaLabel", { name: skill.name })}
                  onClick={() => setReading(skill)}
                >
                  {t("read")}
                </Button>
              }
            />
          </Card>
        ))}
        {reading && (
          <PluginSkillModal
            pluginId={entry.id}
            skill={reading}
            onClose={() => setReading(null)}
          />
        )}
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
  const { mutate } = useSWRConfig();
  const [turnedOn, setTurnedOn] = useState<Skill | null>(null);
  const [sharing, setSharing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const removeModal = useCreateModal();
  const removeCopy = useTranslations("plugins.member.detail.remove");
  const enablement = useSkillEnablement(
    skills.data?.customs ?? [],
    skills.refresh,
    (updated) => {
      if (isPlugin) {
        void detail.refresh();
        void mutate(SWR_KEYS.integrations);
      }
      if (needsAttention(updated.plugin?.needs ?? [])) setTurnedOn(updated);
    }
  );
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
  const syncedFrom =
    skill?.marketplace?.kind === "github" ? skill.marketplace.repository : null;
  const showVersions =
    skill !== undefined &&
    (skill.user_permission === "OWNER" || skill.user_permission === "EDITOR");
  const skillCount = plugin
    ? plugin.skills.length
    : (entry?.skills.length ?? 0);
  const needCount = plugin?.needs.length ?? 0;
  // The supported needs only, as the plugin list counts them.
  const supportedNeedCount =
    plugin?.needs.filter((need) => need.supported).length ?? 0;
  const canEdit =
    skill !== undefined &&
    (skill.user_permission === "OWNER" || skill.user_permission === "EDITOR");
  async function refresh(): Promise<void> {
    await Promise.all([skills.refresh(), isPlugin ? detail.refresh() : null]);
  }

  const tabs: DetailTab<PluginPageTab>[] | null = entry
    ? [
        {
          value: "overview",
          label: t("tabs.overview"),
          content: (
            <OverviewTab
              entry={entry}
              plugin={plugin}
              enablement={enablement}
            />
          ),
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
                label: pageCopy("tabs.integrations", {
                  count: supportedNeedCount,
                }),
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
  async function remove(): Promise<void> {
    if (!skill || removing) return;
    setRemoving(true);
    try {
      await deleteUserSkill(skill.id);
      refreshLists();
      toast.success(removeCopy("done", { name: skill.name }));
      navigation.go(customizeTabHref("plugins"), { replace: true });
    } catch (failure) {
      toast.error(
        failure instanceof Error && failure.message
          ? failure.message
          : removeCopy("failed")
      );
    } finally {
      setRemoving(false);
    }
  }

  const menu: DropdownMenuItem[] = [
    // GitHub holds a synced plugin's files: an upload would make another plugin.
    ...(canEdit && isPlugin && !skill.content_locked
      ? [
          {
            kind: "action" as const,
            id: "upload",
            icon: SvgUploadCloud,
            title: t("actions.uploadVersion"),
            onSelect: () => setUploading(true),
          },
        ]
      : []),
    ...(skill?.can_delete
      ? [
          {
            kind: "group" as const,
            items: [
              {
                kind: "action" as const,
                id: "remove",
                icon: SvgTrash,
                title: t("actions.remove"),
                danger: true,
                onSelect: () => removeModal.toggle(true),
              },
            ],
          },
        ]
      : []),
  ];

  const requested = parsePluginPageTab(searchParams.get("tab"));
  const tab = tabs?.some((item) => item.value === requested)
    ? requested
    : "overview";

  return (
    <CustomizeDetailLayout
      back={
        <BackLink to={customizeTabHref("plugins")} label={tabCopy("plugins")} />
      }
      icon={SvgBlocks}
      title={entry?.name ?? t("title")}
      description={entry?.description ?? undefined}
      tags={
        syncedFrom ? (
          <Badge
            icon={SvgGitHub}
            title={t("syncedFrom", { repository: syncedFrom })}
          />
        ) : undefined
      }
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
              ...(skill && canShareSkill(skill)
                ? [
                    <Button
                      key="share"
                      prominence="secondary"
                      icon={SvgShare}
                      onClick={() => setSharing(true)}
                    >
                      {t("actions.share")}
                    </Button>,
                  ]
                : []),
              ...(menu.length > 0
                ? [
                    <Dropdown key="menu" align="end">
                      <Dropdown.Trigger asChild>
                        <Button
                          prominence="tertiary"
                          icon={SvgMoreHorizontal}
                          aria-label={t("actions.menu")}
                          tooltip={t("actions.menu")}
                        />
                      </Dropdown.Trigger>
                      <Dropdown.Data label={t("actions.menu")} items={menu} />
                    </Dropdown>,
                  ]
                : []),
              <PluginSwitch
                key="switch"
                entry={entry}
                enablement={enablement}
              />,
            ]
          : undefined
      }
    >
      <SkillSwitchModal enablement={enablement} />
      {skill && (
        <ShareSkillModal
          mode="edit"
          skillId={skill.id}
          fallbackTitle={skill.name}
          open={sharing}
          onClose={() => setSharing(false)}
          onSaved={() => void refresh()}
        />
      )}
      <UploadPluginFlow open={uploading} onClose={() => setUploading(false)} />
      <removeModal.Provider>
        {skill && (
          <ConfirmEntityModal
            danger
            entityType={removeCopy("entityType")}
            entityName={skill.name}
            additionalDetails={removeCopy("description")}
            actionButtonText={removeCopy(removing ? "pending" : "submit")}
            onClose={() => {
              if (!removing) removeModal.toggle(false);
            }}
            onSubmit={() => void remove()}
          />
        )}
      </removeModal.Provider>
      {turnedOn && (
        <PluginTurnOnModal
          plugin={turnedOn}
          onClose={() => setTurnedOn(null)}
        />
      )}
    </CustomizeDetailLayout>
  );
}
